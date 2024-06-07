"""
Tiled processing with RVT_py
Created on 6 May 2024
@author: Nejc Čož, ZRC SAZU, Novi trg 2, 1000 Ljubljana, Slovenia
"""

import glob
import multiprocessing as mp
import os
import time
from pathlib import Path

import numpy as np
import rasterio
import rvt.blend
import rvt.default
import rvt.vis
from osgeo import gdal
from rasterio.windows import from_bounds
from rvt.blend_func import normalize_image


def tiled_blending(vis_types, blend_types, input_vrt_path, tiles_list):
    t0 = time.time()

    # Prepare paths
    src_tif_path = Path(input_vrt_path)
    ll_path = src_tif_path.parent

    if tiles_list:
        # Determine nr_processes from available CPUs (leave two free)
        nr_processes = os.cpu_count() - 2
        if nr_processes < 1:
            nr_processes = 1

        # # HERE MULTIPROCESSING STARTS
        #
        # - ds_path  (const) ... for creating output file name
        # - ll_path  (const)
        # - blend_types  (const)
        # - one_tile  (variable)
        #
        # ----------------------------------
        # input_process_list = [(src_tif_path, ll_path, vis_types, blend_types, i) for i in tiles_list]
        # with mp.Pool(nr_processes) as p:
        #     realist = [p.apply_async(compute_save_blends, r) for r in input_process_list]
        #     for result in realist:
        #         pool_out = result.get()
        #         print("Finished tile:", pool_out[1])

        # SINGLE-PROCESS FOR DEBUG
        for one_tile in [tiles_list[3]]:
            result = compute_save_blends(src_tif_path, ll_path, vis_types, blend_types, one_tile)
            print("Finished tile:", result[1])

        # TODO: Build mosaics, need path to folder with tiffs

    else:
        one_tile = None
        result = compute_save_blends(src_tif_path, ll_path, vis_types, blend_types, one_tile)
        print("Finished tile:", result[1])

    # # Build VRTs
    # for ds_dir in [ll_path / i for i in blend_types]:
    #     # Name = <original DEM name> + <visualization (subdir name)> + .vrt
    #     if ds_dir == "e2MSTP" or ds_dir == "e3MSTP":
    #         vrt_name = Path(input_vrt_path).stem + "_" + Path(ds_dir).name + ".vrt"
    #         ds_dir = ds_dir
    #     else:
    #         vrt_name = Path(input_vrt_path).stem + "_" + Path(ds_dir).name + ".vrt"
    #     out_path = build_vrt(ds_dir, vrt_name)
    #     print("  - Created:", out_path)
    # if "e2MSTP" in blend_types:
    #     ds_dir = ll_path / "rrim"
    #     vrt_name = Path(input_vrt_path).stem + "_" + Path(ds_dir).name + ".vrt"
    #     vrt_path = ds_dir.parents[0] / vrt_name
    #     if not vrt_path.exists():
    #         out_path = build_vrt(ds_dir, vrt_name)
    #         print("  - Created:", out_path)
    # if "e3MSTP" in blend_types:
    #     ds_dir = ll_path / "crim"
    #     vrt_name = Path(input_vrt_path).stem + "_" + Path(ds_dir).name + ".vrt"
    #     vrt_path = ds_dir.parents[0] / vrt_name
    #     if not vrt_path.exists():
    #         out_path = build_vrt(ds_dir, vrt_name)
    #         print("  - Created:", out_path)

    t1 = time.time() - t0
    print(f"Done with computing blends in {round(t1/60, ndigits=None)} min.")


def compute_save_blends(src_path, low_levels_path, vis_types, blend_types, one_extent):

    # Prepare filenames for saving
    if one_extent:
        # Determine name of the tile (coordinates)
        one_tile_name = f"{one_extent[0]:.0f}_{one_extent[1]:.0f}"
        # This dictionary will be used to save director
    else:
        one_tile_name = None
    # Filename that will be use RVT built-in function for naming
    filename_rvt = src_path.name
    # ********** COMPUTE LOW-LEVELS *****************************************************

    # Determine req. low-level vis (vis_types from input + req. by blends)
    req_arrays = get_required_arrays(vis_types, blend_types)

    # Default 1 is for GENERAL
    default_1 = rvt.default.DefaultValues()
    # Read from file, path is relative to the Current script directory
    def1_pth = Path(__file__).resolve().parent / "default_1.json"
    default_1.read_default_from_file(def1_pth)

    default_1.fill_no_data = 1
    default_1.keep_original_no_data = 0

    # Default 2 is for FLAT
    default_2 = rvt.default.DefaultValues()
    # Read from file, path is relative to the Current script directory
    def2_pth = Path(__file__).resolve().parent / "default_2.json"
    default_2.read_default_from_file(def2_pth)

    default_2.fill_no_data = 1
    default_2.keep_original_no_data = 0

    # Only compute required visualizations
    in_arrays = compute_low_levels(
        default_1,
        default_2,
        src_path,
        one_extent,
        req_arrays
    )

    # ********** COMPUTE & SAVE SELECTED VISUALIZATIONS *****************************************************
    for vis in vis_types:
        # Determine save path
        if not one_tile_name:
            # Use RVT naming if this is a single image
            save_path = low_levels_path / getattr(default_1, "get_" + vis + "_path")(filename_rvt)
        else:
            # Use tile naming if this is only one tile
            save_path = low_levels_path / vis / f"{one_tile_name}_rvt_{vis}.tif"
            save_path.parent.mkdir(exist_ok=True)

        # Convert to byte scale and save to disk
        vis_bytscl_save(in_arrays, vis, default_1, save_path)

    # ********** COMPUTE & SAVE SELECTED BLENDS *****************************************************

    # Calculate selected BLENDS
    if "vat_combined_8bit" in blend_types:
        # Determine save path
        save_path = save_path_for_blend(
            save_filename="VAT_combined_8bit",
            save_dir=low_levels_path,
            source_filename=filename_rvt,
            save_tile_name=one_tile_name
        )
        # Run VAT Combined 8bit blend
        in_arrays["vat_combined_8bit"] = vat_combined_8bit(in_arrays, save_path)

    # if "VAT_flat_3B" in blend_types:
    #     # Determine save path
    #     save_path = low_levels_path / "VAT_flat_3B" / f"{one_tile}_rvt_VAT_flat_3B.tif"
    #     save_path.parent.mkdir(exist_ok=True)
    #     in_arrays["vat_flat_3bands"] = vat_flat_3bands(in_arrays, save_path)

    # if "VAT_3B" in blend_types:
    #     # Determine save path
    #     save_path = low_levels_path / "VAT_3B" / f"{one_tile}_rvt_VAT_3B.tif"
    #     save_path.parent.mkdir(exist_ok=True)
    #     in_arrays["vat_3bands"] = vat_3bands(in_arrays, save_path)

    # if "VAT_combined_3B" in blend_types:
    #     # Determine save path
    #     save_path = low_levels_path / "VAT_combined_3B" / f"{one_tile}_rvt_VAT_combined_3B.tif"
    #     save_path.parent.mkdir(exist_ok=True)
    #     vat_combined_3bands(in_arrays, save_path)

    if "rrim" in blend_types:
        # Determine save path
        save_path = save_path_for_blend(
            save_filename="RRIM",
            save_dir=low_levels_path,
            source_filename=filename_rvt,
            save_tile_name=one_tile_name
        )
        # Run RRIM blend
        in_arrays["rrim"] = blend_rrim(in_arrays, save_path)

    if "e2MSTP" in blend_types:
        if "rrim" not in in_arrays.keys():
            in_arrays["rrim"] = blend_rrim(in_arrays)
        # Determine save path
        save_path = save_path_for_blend(
            save_filename="e2MSTP",
            save_dir=low_levels_path,
            source_filename=filename_rvt,
            save_tile_name=one_tile_name
        )
        # Run e2MSTP blend
        blend_e2mstp(in_arrays, save_path)

    if "crim" in blend_types:
        # Determine save path
        save_path = save_path_for_blend(
            save_filename="CRIM",
            save_dir=low_levels_path,
            source_filename=filename_rvt,
            save_tile_name=one_tile_name
        )
        # Run CRIM blend
        in_arrays["crim"] = blend_crim(in_arrays, save_path)

    if "e3MSTP" in blend_types:
        # Check if CRIM was already calculated
        if "crim" not in in_arrays.keys():
            in_arrays["crim"] = blend_crim(in_arrays)
        # Determine save path
        save_path = save_path_for_blend(
            save_filename="e3MSTP",
            save_dir=low_levels_path,
            source_filename=filename_rvt,
            save_tile_name=one_tile_name
        )
        # Run e3MSTP blend
        blend_e3mstp(in_arrays, save_path)

    if "e4MSTP" in blend_types:
        # Determine save path
        save_path = save_path_for_blend(
            save_filename="e4MSTP",
            save_dir=low_levels_path,
            source_filename=filename_rvt,
            save_tile_name=one_tile_name
        )
        # Run e4MSTP blend
        blend_e4mstp(in_arrays, save_path)

    return 0, one_tile_name


def vat_combined_8bit(dict_arrays, save_path):
    """
    VAT Combined 8bit
    """
    # BLEND VAT GENERAL
    vat_combination_general = rvt.blend.BlenderCombination()
    vat_combination_general.create_layer(
        vis_method="Sky-View Factor",
        normalization="Value",
        minimum=0.7,
        maximum=1.0,
        blend_mode="Multiply",
        opacity=25,
        image=dict_arrays['svf_1'].squeeze()
    )
    vat_combination_general.create_layer(
        vis_method="Openness - Positive",
        normalization="Value",
        minimum=68,
        maximum=93,
        blend_mode="Overlay",
        opacity=50,
        image=dict_arrays['opns_1'].squeeze()
    )
    vat_combination_general.create_layer(
        vis_method="Slope gradient",
        normalization="Value",
        minimum=0,
        maximum=50,
        blend_mode="Luminosity",
        opacity=50,
        image=dict_arrays['slope_1'].squeeze()
    )
    vat_combination_general.create_layer(
        vis_method="Hillshade",
        normalization="Value",
        minimum=0,
        maximum=1,
        blend_mode="Normal",
        opacity=100,
        image=dict_arrays['hillshade_1'].squeeze()
    )
    vat_1 = vat_combination_general.render_all_images(
        save_visualizations=False,
        save_render_path=None,
        no_data=np.nan
    )
    vat_1 = vat_1.astype("float32")

    # BLEND VAT FLAT
    vat_combination_flat = rvt.blend.BlenderCombination()
    vat_combination_flat.create_layer(
        vis_method="Sky-View Factor",
        normalization="Value",
        minimum=0.9,
        maximum=1.0,
        blend_mode="Multiply",
        opacity=25,
        image=dict_arrays['svf_2'].squeeze()
    )
    vat_combination_flat.create_layer(
        vis_method="Openness - Positive",
        normalization="Value",
        minimum=85,
        maximum=93,
        blend_mode="Overlay",
        opacity=50,
        image=dict_arrays['opns_2'].squeeze()
    )
    vat_combination_flat.create_layer(
        vis_method="Slope gradient",
        normalization="Value",
        minimum=0,
        maximum=15,
        blend_mode="Luminosity",
        opacity=50,
        image=dict_arrays['slope_1'].squeeze()
    )
    vat_combination_flat.create_layer(
        vis_method="Hillshade",
        normalization="Value",
        minimum=0,
        maximum=1,
        blend_mode="Normal",
        opacity=100,
        image=dict_arrays['hillshade_2'].squeeze()
    )
    vat_2 = vat_combination_flat.render_all_images(
        save_visualizations=False,
        save_render_path=None,
        no_data=np.nan
    )
    vat_2 = vat_2.astype("float32")

    # BLEND VAT COMBINED
    comb_vat_combined = rvt.blend.BlenderCombination()
    comb_vat_combined.create_layer(
        vis_method="vat_general", normalization="value",
        minimum=0, maximum=1,
        blend_mode="normal", opacity=50,
        image=vat_1
    )
    comb_vat_combined.create_layer(
        vis_method="vat_flat", normalization="value",
        minimum=0, maximum=1,
        blend_mode="normal", opacity=100,
        image=vat_2
    )
    out_vat_combined = comb_vat_combined.render_all_images(
        save_visualizations=False,
        save_render_path=None,
        no_data=np.nan
    )

    # Convert to 8bit image
    out_vat_combined = rvt.vis.byte_scale(
        out_vat_combined,
        c_min=0,
        c_max=1
    )

    # Save GeoTIF
    out_profile = dict_arrays['profile'].copy()
    out_profile.update(dtype='uint8')
    rasterio_save(
        out_vat_combined,
        out_profile,
        save_path=save_path,
        nodata=None
    )

    return out_vat_combined


def vat_flat_3bands(dict_arrays, save_path):
    """
    SVF (normalised 0.9 – 1)
    Openness positive (normalised 85 – 93)
    Slope gradient (normalised 0° – 15°)
    """

    svf = normalize_image(
        visualization="sky-view factor",
        image=dict_arrays["svf_2"].squeeze(),
        min_norm=0.9,
        max_norm=1,
        normalization="value"
    )
    opns = normalize_image(
        visualization="openness - positive",
        image=dict_arrays["opns_2"].squeeze(),
        min_norm=85,
        max_norm=93,
        normalization="value"
    )
    slope = normalize_image(
        visualization="slope gradient",
        image=dict_arrays["slope_1"].squeeze(),
        min_norm=0,
        max_norm=15,
        normalization="value"
    )
    out_flat_vat3 = np.stack(
        [slope, svf, opns],
        axis=0, out=None
    )

    # Save GeoTIF
    rasterio_save(
        out_flat_vat3,
        dict_arrays['profile'],
        save_path=save_path,
        nodata=np.nan
    )

    return out_flat_vat3


def vat_3bands(dict_arrays, save_path):
    """
    SVF (normalised 0.7 – 1)
    Openness positive (normalised 68 – 93)
    Slope gradient (normalised 0° – 50°)
    """

    svf = normalize_image(
        visualization="sky-view factor",
        image=dict_arrays["svf_1"].squeeze(),
        min_norm=0.7,
        max_norm=1,
        normalization="value"
    )
    opns = normalize_image(
        visualization="openness - positive",
        image=dict_arrays["opns_1"].squeeze(),
        min_norm=68,
        max_norm=93,
        normalization="value"
    )
    slope = normalize_image(
        visualization="slope gradient",
        image=dict_arrays["slope_1"].squeeze(),
        min_norm=0,
        max_norm=50,
        normalization="value"
    )
    out_vat3 = np.stack(
        [slope, svf, opns],
        axis=0, out=None
    )

    # Save GeoTIF
    rasterio_save(
        out_vat3,
        dict_arrays['profile'],
        save_path=save_path,
        nodata=np.nan
    )

    return out_vat3


def vat_combined_3bands(dict_arrays, save_path):
    out_vat_combined_3bands = np.zeros(dict_arrays["vat_3bands"].shape)
    for i in range(3):
        comb_vat_combined_3bands = rvt.blend.BlenderCombination()
        comb_vat_combined_3bands.create_layer(
            vis_method="band1_vat_3bands", normalization="value",
            minimum=0, maximum=1,
            blend_mode="normal", opacity=50,
            image=dict_arrays["vat_3bands"][i, :, :].squeeze()
        )
        comb_vat_combined_3bands.create_layer(
            vis_method="band1_vat_flat_3bands", normalization="value",
            minimum=0, maximum=1,
            blend_mode="normal", opacity=100,
            image=dict_arrays["vat_flat_3bands"][i, :, :].squeeze()
        )
        out_vat_combined_3bands[i, :, :] = comb_vat_combined_3bands.render_all_images(
            save_visualizations=False,
            save_render_path=None,
            no_data=np.nan)

    out_vat_combined_3bands = out_vat_combined_3bands.astype("float32")
    # Save GeoTIF
    rasterio_save(
        out_vat_combined_3bands,
        dict_arrays['profile'],
        save_path=save_path,
        nodata=np.nan
    )

    return out_vat_combined_3bands


def vis_bytscl_save(image_arrays, visualization, defaults, save_path):
    # Adapt to visualization keywords used in in_arrays
    vis_1 = visualization + "_1"

    # Determine min/max values for norm from default.json "bytscl"
    bytscl_value = getattr(defaults, visualization + "_bytscl")
    # Use RVT function for normalization
    out_image = rvt.vis.byte_scale(
        image_arrays[vis_1].squeeze(),
        c_min=bytscl_value[1],
        c_max=bytscl_value[2]
    )

    # Save GeoTIF
    out_profile = image_arrays['profile'].copy()
    out_profile.update(dtype='uint8')
    rasterio_save(
        out_image,
        out_profile,
        save_path=save_path,
        nodata=None
    )
    return out_image


def blend_rrim(dict_arrays, save_path=None):
    comb_rrim = rvt.blend.BlenderCombination()
    comb_rrim.create_layer(vis_method="Slope gradient", normalization="Value",
                           minimum=0, maximum=45,
                           blend_mode="Normal", opacity=50,
                           colormap="Reds_r", min_colormap_cut=0, max_colormap_cut=1,
                           image=dict_arrays['slope_1'].squeeze()
                           )
    comb_rrim.create_layer(vis_method="Opns_Pos_Neg/2", normalization="Value",
                           minimum=-25, maximum=25,
                           blend_mode="Normal", opacity=100,
                           colormap="Greys_r", min_colormap_cut=0, max_colormap_cut=1,
                           image=((dict_arrays['opns_1'] - dict_arrays['neg_opns_1'])/2).squeeze()
                           )
    out_rrim = comb_rrim.render_all_images(save_visualizations=False,
                                           save_render_path=None,
                                           no_data=np.nan)
    out_rrim = out_rrim.astype("float32")
    # Save GeoTIF
    if save_path:
        # Convert to 8bit image
        out_rrim_8bit = rvt.vis.byte_scale(
            out_rrim,
            c_min=0,
            c_max=1
        )

        # Save GeoTIF
        out_profile = dict_arrays['profile'].copy()
        out_profile.update(dtype='uint8')
        rasterio_save(
            out_rrim_8bit,
            out_profile,
            save_path=save_path,
            nodata=None
        )

    return out_rrim


def blend_e2mstp(dict_arrays, save_path):
    comb_e2mstp = rvt.blend.BlenderCombination()
    comb_e2mstp.create_layer(vis_method="slrm", normalization="value",
                             minimum=-0.5, maximum=0.5,
                             blend_mode="screen", opacity=25,
                             image=dict_arrays["slrm_1"].squeeze()
                             )
    comb_e2mstp.create_layer(vis_method="rrim", normalization="value",
                             minimum=0, maximum=1,
                             blend_mode="soft_light", opacity=70,
                             image=dict_arrays["rrim"]
                             )
    comb_e2mstp.create_layer(vis_method="mstp", normalization="value",
                             minimum=0, maximum=1,
                             blend_mode="normal", opacity=100,
                             image=dict_arrays["mstp_1"]
                             )
    out_e2mstp = comb_e2mstp.render_all_images(save_visualizations=False,
                                               save_render_path=None,
                                               no_data=np.nan)
    out_e2mstp = out_e2mstp.astype("float32")
    out_e2mstp[np.isnan(dict_arrays["rrim"])] = np.nan
    out_e2mstp[out_e2mstp > 1] = 1

    # Convert to 8bit image
    out_8bit = rvt.vis.byte_scale(
        out_e2mstp,
        c_min=0,
        c_max=1
    )

    # Save GeoTIF
    out_profile = dict_arrays['profile'].copy()
    out_profile.update(dtype='uint8')
    rasterio_save(
        out_8bit,
        out_profile,
        save_path=save_path,
        nodata=None
    )


def blend_crim(dict_arrays, save_path=None):
    comb_crim = rvt.blend.BlenderCombination()
    comb_crim.create_layer(vis_method="Openness_Pos-Neg", normalization="Value",
                           minimum=-28, maximum=28,
                           blend_mode="overlay", opacity=50,
                           image=(dict_arrays['opns_1'] - dict_arrays['neg_opns_1']).squeeze()
                           )
    comb_crim.create_layer(vis_method="Openness_Pos-Neg", normalization="Value",
                           minimum=-28, maximum=28,
                           blend_mode="luminosity", opacity=50,
                           image=(dict_arrays['opns_1'] - dict_arrays['neg_opns_1']).squeeze()
                           )
    comb_crim.create_layer(vis_method="slope gradient red", normalization="Value",
                           minimum=0, maximum=45,
                           blend_mode="normal", opacity=100,
                           colormap="OrRd", min_colormap_cut=0, max_colormap_cut=1,
                           image=dict_arrays['slope_1'].squeeze()
                           )
    out_crim = comb_crim.render_all_images(save_visualizations=False,
                                           save_render_path=None,
                                           no_data=np.nan)
    out_crim = out_crim.astype("float32")

    # Save GeoTIF
    if save_path:
        # Convert to 8bit image
        out_crim_8bit = rvt.vis.byte_scale(
            out_crim,
            c_min=0,
            c_max=1
        )

        # Save GeoTIF
        out_profile = dict_arrays['profile'].copy()
        out_profile.update(dtype='uint8')
        rasterio_save(
            out_crim_8bit,
            out_profile,
            save_path=save_path,
            nodata=None
        )

    return out_crim


def blend_e3mstp(dict_arrays, save_path):
    comb_e3mstp = rvt.blend.BlenderCombination()
    comb_e3mstp.create_layer(vis_method="slrm", normalization="value",
                             minimum=-0.5, maximum=0.5,
                             blend_mode="screen", opacity=25,
                             image=dict_arrays["slrm_1"].squeeze()
                             )
    comb_e3mstp.create_layer(vis_method="crim", normalization="value",
                             minimum=0, maximum=1,
                             blend_mode="soft_light", opacity=70,
                             image=dict_arrays["crim"]
                             )
    comb_e3mstp.create_layer(vis_method="mstp", normalization="value",
                             minimum=0, maximum=1,
                             blend_mode="normal", opacity=100,
                             image=dict_arrays["mstp_1"]
                             )
    out_e3mstp = comb_e3mstp.render_all_images(save_visualizations=False,
                                               save_render_path=None,
                                               no_data=np.nan)
    out_e3mstp = out_e3mstp.astype("float32")
    out_e3mstp[np.isnan(dict_arrays["crim"])] = np.nan
    out_e3mstp[out_e3mstp > 1] = 1

    # Convert to 8bit image
    out_e3mstp = rvt.vis.byte_scale(
        out_e3mstp,
        c_min=0,
        c_max=1
    )

    # Save GeoTIF
    out_profile = dict_arrays['profile'].copy()
    out_profile.update(dtype='uint8')
    rasterio_save(
        out_e3mstp,
        out_profile,
        save_path=save_path,
        nodata=None
    )


def blend_e4mstp(dict_arrays, save_path):
    # Get Coloured Slope
    dict_arrays['cs'] = blend_coloured_slope(dict_arrays)
    # Get SVF combined
    dict_arrays['svf_combined'] = blend_svf_combined(dict_arrays)
    # Get Openness + LD
    dict_arrays['opns_ld'] = blend_opns_ld(dict_arrays)

    comb_nv = rvt.blend.BlenderCombination()
    comb_nv.create_layer(
        vis_method="mstp",
        normalization="value", minimum=0, maximum=1,
        blend_mode="overlay", opacity=90,
        image=dict_arrays['mstp_1']
    )
    comb_nv.create_layer(
        vis_method="Comb svf",
        normalization="value", minimum=-0.5, maximum=0.5,
        blend_mode="multiply", opacity=25,
        image=dict_arrays['svf_combined']
    )
    comb_nv.create_layer(
        vis_method="Comb openness LD",
        normalization="value", minimum=0, maximum=1,
        blend_mode="multiply", opacity=100,
        image=dict_arrays['opns_ld']
    )
    comb_nv.create_layer(
        vis_method="coloured slope",
        normalization="value", minimum=0, maximum=1,
        blend_mode="normal", opacity=100,
        image=dict_arrays['cs']
    )
    out_e4mstp = comb_nv.render_all_images(
        save_visualizations=False,
        save_render_path=None,
        no_data=np.nan
    )
    out_e4mstp = out_e4mstp.astype("float32")
    out_e4mstp[np.isnan(dict_arrays['mstp_1'])] = np.nan
    out_e4mstp[out_e4mstp > 1] = 1

    # Convert to 8bit image
    out_e4mstp = rvt.vis.byte_scale(
        out_e4mstp,
        c_min=0,
        c_max=1
    )

    # Save GeoTIF
    out_profile = dict_arrays['profile'].copy()
    out_profile.update(dtype='uint8')
    rasterio_save(
        out_e4mstp,
        out_profile,
        save_path=save_path,
        nodata=None
    )

    return out_e4mstp


def blend_coloured_slope(dict_arrays, save_path=None):
    # Coloured slope
    comb_cs = rvt.blend.BlenderCombination()
    comb_cs.create_layer(
        vis_method="Slope gradient", normalization="Value",
        minimum=0, maximum=55,
        blend_mode="normal", opacity=100,
        colormap="Reds_r", min_colormap_cut=0, max_colormap_cut=1,
        image=dict_arrays['slope_1'].squeeze()
    )
    coloured_slope = comb_cs.render_all_images(
        save_visualizations=False,
        save_render_path=None,
        no_data=np.nan
    )
    coloured_slope = coloured_slope.astype("float32")

    if save_path:
        # Save GeoTIF
        rasterio_save(
            coloured_slope,
            dict_arrays['profile'],
            save_path=save_path,
            nodata=np.nan
        )

    return coloured_slope


def blend_opns_ld(dict_arrays, save_path=None):
    """Required dict_arrays:
    - opns
    - neg_opns
    - ld
    """
    comb = rvt.blend.BlenderCombination()
    comb.create_layer(
        vis_method="Openness difference", normalization="Value",
        minimum=-15, maximum=15,
        blend_mode="normal", opacity=50,
        image=(dict_arrays['opns_1'] - dict_arrays['neg_opns_1']).squeeze()
    )
    comb.create_layer(
        vis_method="Local dominance", normalization="Value",
        minimum=0.5, maximum=1.8,
        blend_mode="normal", opacity=100,
        image=dict_arrays['ld_1'].squeeze()
    )
    opns_ld = comb.render_all_images(
        save_visualizations=False,
        save_render_path=None,
        no_data=np.nan
    )
    opns_ld = opns_ld.astype("float32")

    if save_path:
        # Save GeoTIF
        rasterio_save(
            opns_ld,
            dict_arrays['profile'],
            save_path=save_path,
            nodata=np.nan
        )

    return opns_ld


def blend_svf_combined(dict_arrays, save_path=None):
    """Required dict_arrays:
    - svf_1
    - svf_2
    """
    comb_svf = rvt.blend.BlenderCombination()
    comb_svf.create_layer(vis_method="Sky-view factor", normalization="Value",
                          minimum=0.7, maximum=1,
                          blend_mode="normal", opacity=50,
                          image=dict_arrays['svf_1'].squeeze()
                          )
    comb_svf.create_layer(vis_method="Sky-view factor", normalization="Value",
                          minimum=0.9, maximum=1,
                          blend_mode="normal", opacity=100,
                          image=dict_arrays['svf_2'].squeeze()
                          )
    cs_svf = comb_svf.render_all_images(save_visualizations=False,
                                        save_render_path=None,
                                        no_data=np.nan)
    cs_svf = cs_svf.astype("float32")

    if save_path:
        # Save GeoTIF
        rasterio_save(
            cs_svf,
            dict_arrays['profile'],
            save_path=save_path,
            nodata=np.nan
        )

    return cs_svf


def rasterio_save(array, profile, save_path, nodata=None):
    if len(array.shape) == 2:
        array = np.expand_dims(array, axis=0)
    profile.update(dtype=array.dtype,
                   count=array.shape[0],
                   nodata=nodata,
                   compress="LZW",
                   predictor=2)
    with rasterio.open(save_path, "w", **profile) as dst:
        dst.write(array)


def get_required_arrays(vis_types, blend_types):
    # Initialize dict with all possible visualizations
    # NOTE: The keys with "_1" have to match the input values of visualizations in GUI!!!
    req_arrays = {
        # These are visualizations (also GENERAL for VAT):
        "slope_1": False,
        "hillshade_1": False,
        "multi_hillshade_1": False,
        "slrm_1": False,
        "svf_1": False,  # large = FLAT = 5m
        "opns_1": False,
        "neg_opns_1": False,
        "ld_1": False,
        "sky_illumination_1": False,
        "shadow_horizon_1": False,
        "msrm_1": False,
        "mstp_1": False,

        # Flat terrain:
        "hillshade_2": False,
        "svf_2": False,  # large = FLAT = 10m
        "opns_2": False,
        "neg_opns_2": False
    }

    # Update dictionary based on given visualizations:
    for key in vis_types:
        key = key + "_1"
        if key in req_arrays:
            req_arrays[key] = True

    # Update dictionary based on given blends:
    # if "VAT_3B" in blend_types:
    #     req_arrays["svf_1"] = True
    #     req_arrays["opns_1"] = True
    #     req_arrays["slope_1"] = True

    # if "VAT_flat_3B" in blend_types:
    #     req_arrays["svf_2"] = True
    #     req_arrays["opns_2"] = True
    #     req_arrays["slope_1"] = True

    # if "VAT_combined_3B" in blend_types:
    #     req_arrays["svf_2"] = True
    #     req_arrays["opns_2"] = True
    #     req_arrays["svf_1"] = True
    #     req_arrays["opns_1"] = True
    #     req_arrays["slope_1"] = True

    if ("e3MSTP" in blend_types) or ("e2MSTP" in blend_types):
        req_arrays["slrm_1"] = True
        req_arrays["mstp_1"] = True
        req_arrays["slope_1"] = True
        req_arrays["opns_1"] = True
        req_arrays["neg_opns_1"] = True

    if "e4MSTP" in blend_types:
        req_arrays["ld_1"] = True
        req_arrays["svf_1"] = True,
        req_arrays["mstp_1"] = True
        req_arrays["svf_2"] = True
        req_arrays["opns_2"] = True
        req_arrays["opns_1"] = True
        req_arrays["neg_opns_1"] = True
        req_arrays["slope_1"] = True

    if "vat_combined_8bit" in blend_types:
        req_arrays["svf_2"] = True
        req_arrays["opns_2"] = True
        req_arrays["svf_1"] = True
        req_arrays["opns_1"] = True
        req_arrays["slope_1"] = True
        req_arrays["hillshade_1"] = True
        req_arrays["hillshade_2"] = True

    if "rrim" in blend_types:
        req_arrays["slope_1"] = True
        req_arrays["opns_1"] = True
        req_arrays["neg_opns_1"] = True

    return req_arrays


def compute_low_levels(
        default_1,
        default_2,
        vrt_path,
        input_dem_extents,
        vis_types
):
    # Read buffer values from defaults (already changed from meters to pixels!!!)!
    all_buffers = {
        "slope_1": 0,
        "slrm_1": default_1.slrm_rad_cell,
        "ld_1": default_1.ld_max_rad,
        "mstp_1": default_1.mstp_broad_scale[1],

        "hillshade_1": 1,
        "hillshade_2": 1,

        "svf_GEN": default_1.svf_r_max,  # SVF, OPNS+ and OPNS- for (GENERAL = SMALL = 5m)

        "svf_FLAT": default_2.svf_r_max,  # SVF, OPNS+ and OPNS- for (FLAT = LARGE = 10m)
    }

    # Get required visualizations (account for SVF, opns and neg.opns, they are calculated in the same function)
    req_visualizations = [a for (a, v) in vis_types.items() if v]
    if any(value in req_visualizations for value in ["svf_1", "opns_1", "neg_opns_1"]):
        req_visualizations.append("svf_GEN")
    if any(value in req_visualizations for value in ["svf_2", "opns_2", "neg_opns_2"]):
        req_visualizations.append("svf_FLAT")

    # Filter buffer_dict based on required visualizations
    buffer_dict = {key: all_buffers[key] for key in req_visualizations if key in all_buffers}

    # Select the largest required buffer
    max_buff = max(buffer_dict, key=buffer_dict.get)
    buffer = buffer_dict[max_buff]

    # Read array into RVT dictionary format
    dict_arrays = get_raster_vrt(vrt_path, input_dem_extents, buffer)

    # Change nodata value to np.nan, to avoid problems later
    dict_arrays["array"][dict_arrays["array"] == dict_arrays["no_data"]] = np.nan
    dict_arrays["no_data"] = np.nan

    # --- START VISUALIZATION WITH RVT ---
    vis_out = dict()
    for vis_type in buffer_dict:
        # Obtain buffer for current visualization type
        arr_buff = buffer_dict[vis_type]
        # Slice raster to minimum required size
        arr_slice = buffer_dict[max_buff] - arr_buff
        if arr_slice == 0:
            sliced_arr = dict_arrays["array"]
        else:
            sliced_arr = dict_arrays["array"][arr_slice:-arr_slice, arr_slice:-arr_slice]

        # Run visualization
        if vis_type == "slope_1":
            vis_out = {
                vis_type: default_1.get_slope(
                    sliced_arr,
                    resolution_x=dict_arrays["resolution"][0],
                    resolution_y=dict_arrays["resolution"][1]
                )
            }
        elif vis_type == "slrm_1":
            vis_out = {
                vis_type: default_1.get_slrm(sliced_arr)
            }
        elif vis_type == "ld_1":
            vis_out = {
                vis_type: default_1.get_local_dominance(sliced_arr)
            }
        elif vis_type == "mstp_1":
            # test = default_1.get_slrm(sliced_arr)
            vis_out = {
                # vis_type: np.stack((test, test, test), 0)
                vis_type: default_1.get_mstp(sliced_arr)
            }
        elif vis_type == "hillshade_1":
            vis_out = {
                vis_type: default_1.get_hillshade(
                    sliced_arr,
                    resolution_x=dict_arrays["resolution"][0],
                    resolution_y=dict_arrays["resolution"][1]
                )
            }
        elif vis_type == "hillshade_2":
            vis_out = {
                vis_type: default_2.get_hillshade(
                    sliced_arr,
                    resolution_x=dict_arrays["resolution"][0],
                    resolution_y=dict_arrays["resolution"][1]
                )
            }
        elif vis_type == "svf_GEN":  # small, GENERAL, 5m
            # Check which of the 3 to be computed
            compute_svf = True if "svf_1" in req_visualizations else False
            compute_opns = True if "opns_1" in req_visualizations else False
            compute_neg_opns = True if "neg_opns_1" in req_visualizations else False

            vis_out = {}

            if compute_svf or compute_opns:
                vis_out = default_1.get_sky_view_factor(
                    sliced_arr,
                    dict_arrays["resolution"][0],
                    compute_svf=compute_svf,
                    compute_opns=compute_opns
                )
                # Rename to correct vis_type (which svf is this?)
                for k in list(vis_out.keys()):
                    vis_out[f"{k}_1"] = vis_out.pop(k)

            if compute_neg_opns:
                vis_out["neg_opns_1"] = default_1.get_neg_opns(
                    sliced_arr,
                    dict_arrays["resolution"][0]
                )
        elif vis_type == "svf_FLAT":  # large, FLAT, 10m
            # Check which of the 3 to be computed
            compute_svf = True if "svf_2" in req_visualizations else False
            compute_opns = True if "opns_2" in req_visualizations else False
            compute_neg_opns = True if "neg_opns_2" in req_visualizations else False

            vis_out = {}

            if compute_svf or compute_opns:
                vis_out = default_1.get_sky_view_factor(
                    sliced_arr,
                    dict_arrays["resolution"][0],
                    compute_svf=compute_svf,
                    compute_opns=compute_opns
                )
                # Rename to correct vis_type (which svf is this?)
                for k in list(vis_out.keys()):
                    vis_out[f"{k}_2"] = vis_out.pop(k)

            if compute_neg_opns:
                vis_out["neg_opns_2"] = default_1.get_neg_opns(
                    sliced_arr,
                    dict_arrays["resolution"][0]
                )
        else:
            raise ValueError("Wrong vis_type in the visualization for loop")

        # Remove buffer and Store visualization in dictionary
        for i, array in vis_out.items():
            # Slice away buffer
            if arr_buff == 0:
                arr_out = array
            else:
                arr_out = array[..., arr_buff:-arr_buff, arr_buff:-arr_buff]

            # Make sure the dimensions of array are correct
            if arr_out.ndim == 2:
                arr_out = np.expand_dims(arr_out, axis=0)

            # Add to results dictionary
            dict_arrays[i] = arr_out

    return dict_arrays


def get_raster_vrt(vrt_path, extents, buffer):
    """
    Extents have to be transformed into rasterio Window object, it is passed into the function as tuple.
    (left, bottom, right, top)


    Parameters
    ----------
    vrt_path : str
        Path to raster file. Can be any rasterio readable format.
    extents : tuple
        Extents to be read (left, bottom, right, top).
    buffer : int
        Buffer in pixels.

    Returns
    -------
        A dictionary containing the raster array and all the required metadata.

    """
    with rasterio.open(vrt_path) as vrt:
        # If extents are not given, use source extents
        extents = list(vrt.bounds)

        # Read VRT metadata
        vrt_res = vrt.res
        vrt_nodata = vrt.nodata
        vrt_transform = vrt.transform
        vrt_crs = vrt.crs

        # ADD BUFFER TO EXTENTS (LBRT) - transform pixels to meters!
        buffer_m = buffer * vrt_res[0]
        buff_extents = (
            extents[0] - buffer_m,
            extents[1] - buffer_m,
            extents[2] + buffer_m,
            extents[3] + buffer_m
        )

        # Pack extents into rasterio's Window object
        buff_window = from_bounds(*buff_extents, vrt_transform)
        orig_window = from_bounds(*extents, vrt_transform)

        # Read windowed array (with added buffer)
        # boundless - if window falls out of bounds, read it and fill with NaNs
        win_array = vrt.read(window=buff_window, boundless=True)

        # Save transform object of both extents (original and buffered)
        buff_transform = vrt.window_transform(buff_window)
        orig_transform = vrt.window_transform(orig_window)

    # For raster with only one band, remove first axis from the array (RVT requirement)
    if win_array.shape[0] == 1:
        win_array = np.squeeze(win_array, axis=0)

    # Prepare output metadata profile
    out_profile = {
        'driver': 'GTiff',
        'nodata': None,
        'width':  win_array.shape[1] - 2 * buffer,
        'height':  win_array.shape[0] - 2 * buffer,
        'count':  1,
        'crs': vrt_crs,
        'transform': orig_transform,
        "compress": "lzw"
    }

    output = {
        "array": win_array,
        "resolution": vrt_res,
        "no_data": vrt_nodata,
        "buff_transform": buff_transform,
        "orig_transform": orig_transform,
        "crs": vrt_crs,
        "profile": out_profile
    }

    return output


def build_vrt(ds_dir, vrt_name):
    ds_dir = Path(ds_dir)
    vrt_path = ds_dir.parents[0] / vrt_name
    tif_list = glob.glob(Path(ds_dir / "*.tif").as_posix())

    vrt_options = gdal.BuildVRTOptions()
    my_vrt = gdal.BuildVRT(vrt_path.as_posix(), tif_list, options=vrt_options)
    my_vrt = None

    return vrt_path


def save_path_for_blend(save_filename: str, save_dir, source_filename, save_tile_name=None):
    """
    Two options for creating save path:

    - if single TIF, save the raster using the path to the final save file (located in the same folder as source file
        and using RVT naming conventions). In this case the save_tile_name variable is given as None

    - in the case where we want to save only the one tile, use the constructed save_tile_name and save into a child
        directory of the same name as the final name of the save file
    """
    save_dir = Path(save_dir)
    source_filename = Path(source_filename)
    # Determine save path
    if not save_tile_name:
        # Use RVT naming if this is a single image
        save_path = save_dir / f"{source_filename.stem}_{save_filename}.tif"
    else:
        # Use tile naming if this is only one tile
        save_path = save_dir / save_filename / f"{save_tile_name}_rvt_{save_filename}.tif"
        save_path.parent.mkdir(exist_ok=True)
    return save_path
