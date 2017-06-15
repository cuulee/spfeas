#!/usr/bin/env python

import os
import sys
# import time
# import platform
# import copy
# import itertools
import fnmatch
from joblib import Parallel, delayed

from .sphelpers import sputilities
from . import spsplit
from .sphelpers import spreshape
from .spfunctions import get_mag_avg
from . import errors

from mpglue import raster_tools, VegIndicesEquations, vrt_builder

# YAML
try:
    import yaml
except ImportError:
    raise ImportError('YAML must be installed')

# NumPy
try:
    import numpy as np
except ImportError:
    raise ImportError('NumPy must be installed')


def _write_section2file(this_parameter_object__, meta_info, section2write, 
                        i_sect, j_sect, section_counter):
    
    errors.logger.info('  Writing section {:d} to file ...'.format(section_counter))

    o_info = meta_info.copy()

    section_shape = section2write.shape

    o_info = sputilities.get_output_info_tile(meta_info, 
                                              o_info, 
                                              this_parameter_object__,
                                              i_sect, 
                                              j_sect,
                                              section_shape)

    if not isinstance(section2write, np.ndarray):

        section2write = np.zeros((o_info.bands,
                                  o_info.rows,
                                  o_info.cols), dtype='uint8')

    start_band = this_parameter_object__.band_info[this_parameter_object__.trigger]
    n_bands = this_parameter_object__.out_bands_dict[this_parameter_object__.trigger]

    if os.path.isfile(this_parameter_object__.out_img):

        # Open the file and write the new bands.
        with raster_tools.ropen(this_parameter_object__.out_img, open2read=False) as out_raster:

            # Write each scale and feature.
            for feature_band in range(start_band, start_band+n_bands+1):
                out_raster.write_array(section2write[feature_band-1, 1:, 1:], band=feature_band)

    else:

        # Create the output raster.
        with raster_tools.create_raster(this_parameter_object__.out_img, o_info) as out_raster:

            # Write each scale and feature.
            for feature_band in range(start_band, start_band+n_bands):
                out_raster.write_array(section2write[feature_band-1, 1:, 1:], band=feature_band)

    out_raster = None

    # Check if any of the bands are corrupted.
    with raster_tools.ropen(this_parameter_object__.out_img) as ob_info:

        ob_info.check_corrupted_bands()

        # Open the status YAML file.
        mts_ = sputilities.ManageStatus()

        # Load the status dictionary
        mts_.status_file = this_parameter_object__.status_file
        mts_.load_status()

        if ob_info.corrupted_bands:
            mts_.status_dict[this_parameter_object__.out_img_base] = 'corrupt'
        else:
            mts_.status_dict[this_parameter_object__.out_img_base] = 'complete'

        mts_.dump_status()

    ob_info = None


def _section_read_write(section_counter, section_pair):
    
    this_parameter_object_ = this_parameter_object.copy()

    this_parameter_object_.update_info(section_counter=section_counter)

    # Set the output name.
    this_parameter_object_ = sputilities.scale_fea_check(this_parameter_object_)

    # Open the status YAML file.
    mts_ = sputilities.ManageStatus()

    # Load the status dictionary
    mts_.status_file = this_parameter_object_.status_file
    mts_.load_status()

    # Check file status.
    if os.path.isfile(this_parameter_object_.out_img):

        # The file has been processed.
        if this_parameter_object_.out_img_base in mts_.status_dict:

            if mts_.status_dict[this_parameter_object_.out_img_base] == 'complete':

                if this_parameter_object_.overwrite:

                    os.remove(this_parameter_object_.out_img)
                    mts_.status_dict[this_parameter_object_.out_img_base] = 'incomplete'

                else:
                    return

            elif mts_.status_dict[this_parameter_object_.out_img_base] == 'corrupt':

                os.remove(this_parameter_object_.out_img)
                mts_.status_dict[this_parameter_object_.out_img_base] = 'incomplete'

        else:

            os.remove(this_parameter_object_.out_img)
            mts_.status_dict[this_parameter_object_.out_img_base] = 'incomplete'

    i_sect = section_pair[0]
    j_sect = section_pair[1]

    n_rows = raster_tools.n_rows_cols(i_sect, this_parameter_object_.sect_row_size, this_image_info.rows)
    n_cols = raster_tools.n_rows_cols(j_sect, this_parameter_object_.sect_col_size, this_image_info.cols)

    # Open the image array.
    # TODO: add other indices
    if this_parameter_object_.trigger in ['ndvi', 'evi2']:

        sect_in = this_image_info.read(bands2open=[this_parameter_object_.band_red,
                                                   this_parameter_object_.band_nir],
                                       i=i_sect,
                                       j=j_sect,
                                       rows=n_rows,
                                       cols=n_cols,
                                       d_type='float32')

        vie = VegIndicesEquations(sect_in, chunk_size=-1)
        sect_in = vie.compute(this_parameter_object_.trigger.upper(), out_type=2)

        this_parameter_object_.min = 0
        this_parameter_object_.max = 255

    elif this_parameter_object_.trigger == 'dmp':

        sect_in = np.asarray([this_image_info.read(bands2open=dmp_bd,
                                                   i=i_sect,
                                                   j=j_sect,
                                                   rows=n_rows,
                                                   cols=n_cols,
                                                   d_type='float32')
                              for dmp_bd in range(1, this_image_info.bands+1)]).reshape(this_image_info.bands,
                                                                                        n_rows,
                                                                                        n_cols)

    elif this_parameter_object_.trigger == 'saliency':

        sect_in = spsplit.saliency(this_image_info,
                                   this_parameter_object_,
                                   i_sect,
                                   j_sect,
                                   n_rows,
                                   n_cols)

    elif this_parameter_object_.trigger == 'grad':

        sect_in, __, __ = sputilities.convert_rgb2gray(this_image_info,
                                                       i_sect,
                                                       j_sect,
                                                       n_rows,
                                                       n_cols)

        sect_in = get_mag_avg(sect_in)
        this_parameter_object_.update_info(min=0, max=255)

    elif this_parameter_object_.use_rgb and this_parameter_object_.trigger not in ['grad', 'ndvi', 'evi2', 'dmp', 'saliency']:

        sect_in, __, __ = sputilities.convert_rgb2gray(this_image_info,
                                                       i_sect,
                                                       j_sect,
                                                       n_rows,
                                                       n_cols)

    else:

        sect_in = this_image_info.read(bands2open=this_parameter_object_.band_position,
                                       i=i_sect,
                                       j=j_sect,
                                       rows=n_rows,
                                       cols=n_cols)

    # Pad the array.
    #   (top, bottom), (left, right)
    this_parameter_object_.update_info(i_sect_blk_ctr=1,
                                       j_sect_blk_ctr=1)

    sect_in = sputilities.pad_array(this_parameter_object_, sect_in, n_rows, n_cols)

    if this_parameter_object_.trigger == 'dmp':

        l_rows, l_cols = sect_in[0].shape
        oR, oC, out_rows, out_cols = spsplit.get_out_dims(l_rows,
                                                          l_cols,
                                                          this_parameter_object_)
    else:

        l_rows, l_cols = sect_in.shape
        oR, oC, out_rows, out_cols = spsplit.get_out_dims(l_rows,
                                                          l_cols,
                                                          this_parameter_object_)

    # out_section_array = None

    # Only extract features if the section hasn't
    #   been completed or if the section does not
    #   contain all zeros.
    # if sect_in.max() > 0:

    # Here we split the current section into
    #   chunks and process the features.

    # Split image and compute features.
    section_stats_array = spsplit.get_section_stats(sect_in,
                                                    l_rows,
                                                    l_cols,
                                                    this_parameter_object_)

    # Reshape list of features into
    #   <features x rows x columns> array.
    out_section_array = spreshape.chunks2section(this_parameter_object_.trigger,
                                                 section_stats_array,
                                                 oR,
                                                 oC,
                                                 l_rows,
                                                 l_cols,
                                                 out_rows,
                                                 out_cols,
                                                 this_parameter_object_)

    _write_section2file(this_parameter_object_,
                        this_image_info,
                        out_section_array,
                        i_sect,
                        j_sect,
                        section_counter)

    this_parameter_object_ = None
    this_image_info_ = None


def run(parameter_object):

    """
    Args:
        input_image, output_dir, band_positions=[1], use_rgb=False, block=2, scales=[8], triggers=['mean'],
        threshold=20, min_len=10, line_gap=2, weighted=False, sfs_thresh=80, resamp_sfs=0.,
        equalize=False, equalize_adapt=False, smooth=0, visualize=False, convert_stk=False, gdal_cache=256,
        do_pca=False, stack_feas=True, stack_only=False, band_red=3, band_nir=4, neighbors=False, n_jobs=-1,
        reset_sects=False, image_max=0, lac_r=2, section_size=8000, chunk_size=512
    """

    global this_parameter_object, this_image_info

    sputilities.parameter_checks(parameter_object)

    # Write the parameters to file.
    sputilities.write_log(parameter_object)

    if parameter_object.stack_only:

        new_feas_list = list()

        # If prompted, stack features without processing.
        parameter_object = sputilities.stack_features(parameter_object, new_feas_list)

    else:

        # Create the status object.
        mts = sputilities.ManageStatus()
        mts.status_file = parameter_object.status_file

        # Setup the status dictionary.
        if os.path.isfile(parameter_object.status_file):
            mts.load_status()
        else:

            mts.status_dict = dict()

            mts.status_dict['all_finished'] = 'no'

            mts.status_dict['band_order'] = dict()

            # Save the band order.
            for trigger in parameter_object.triggers:

                mts.status_dict['band_order']['{}'.format(trigger)] = '{:d}-{:d}'.format(parameter_object.band_info[trigger],
                                                                                         parameter_object.band_info[trigger]+parameter_object.out_bands_dict[trigger])

            mts.dump_status()

        process_image = True

        if 'all_finished' in mts.status_dict:

            if mts.status_dict['all_finished'] == 'yes':
                process_image = False

        # Set the output features folder.
        parameter_object = sputilities.set_feas_dir(parameter_object)

        if not process_image:
            errors.logger.warning('The input image, {}, is set as finished processing.'.format(parameter_object.input_image))
        else:

            # Iterate over each feature trigger.
            for trigger in parameter_object.triggers:

                parameter_object.update_info(trigger=trigger)

                # Iterate over each band
                for band_position in parameter_object.band_positions:

                    parameter_object.update_info(band_position=band_position)

                    # Get the input image information.
                    with raster_tools.ropen(parameter_object.input_image) as i_info:

                        # Check if any of the input
                        #   bands are corrupted.
                        i_info.check_corrupted_bands()

                        if i_info.corrupted_bands:

                            errors.logger.error('\nThe following bands appear to be corrupted:\n{}'.format(', '.join(i_info.corrupted_bands)))
                            raise errors.CorruptedBandsError

                        # Get image statistics.
                        parameter_object = sputilities.get_stats(i_info, parameter_object)

                        # Get section and chunk size.
                        parameter_object = sputilities.get_sect_chunk_size(i_info, parameter_object)

                        # Get the number of sections in
                        #   the image (only used as a counter).
                        parameter_object = sputilities.get_n_sects(i_info, parameter_object)

                        this_parameter_object = parameter_object.copy()
                        this_image_info = i_info.copy()

                        Parallel(n_jobs=parameter_object.n_jobs_section,
                                 max_nbytes=None)(delayed(_section_read_write)(idx_pair,
                                                                               parameter_object.section_idx_pairs[idx_pair-1])
                                                  for idx_pair in range(1, parameter_object.n_sects+1))

                    i_info = None

        # Check the corruption status
        mts.load_status()

        any_corrupt = False

        for k, v in mts.status_dict.items():

            if v == 'corrupt':

                any_corrupt = True
                break

        if not any_corrupt:

            mts.status_dict['all_finished'] = 'yes'
            mts.dump_status()

        # Finally, mosaic the image tiles.
        if mts.status_dict['all_finished'] == 'yes':

            comp_dict = dict()

            # Get the image list.
            parameter_object = sputilities.scale_fea_check(parameter_object, is_image=False)

            image_list = fnmatch.filter(os.listdir(parameter_object.feas_dir), parameter_object.search_wildcard)
            image_list = [os.path.join(parameter_object.feas_dir, im) for im in image_list]

            comp_dict['1'] = image_list

            errors.logger.info('\nCreating the VRT mosaic ...')

            vrt_mosaic = parameter_object.status_file.replace('.yaml', '.vrt')

            vrt_builder(comp_dict,
                        vrt_mosaic,
                        force_type='float32',
                        be_quiet=True,
                        overwrite=True)

            if parameter_object.overviews:

                errors.logger.info('\nBuilding VRT overviews ...')

                with raster_tools.ropen(vrt_mosaic, open2read=False) as vrt_info:

                    vrt_info.remove_overviews()
                    vrt_info.build_overviews(levels=[2, 4, 8, 16])

                vrt_info = None
