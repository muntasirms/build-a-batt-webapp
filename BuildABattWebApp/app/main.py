import os
import uuid
import shutil
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app.generator import FlowCellGenerator
from build123d import export_stl, export_step, ExportDXF, extrude

app = FastAPI(title="Build a Batt API")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

class CellParameters(BaseModel):
    plate_x: float = 200.0
    plate_y: float = 200.0
    plate_z_flow: float = 1.0
    electrode_x: float = 130.0
    electrode_y: float = 130.0
    manifold_wall_thickness: float = 0.0
    manifold_max_width: float = 15.0
    manifold_min_width: float = 10.0
    distribution_length: float = 0.0
    distribution_growth_rate: float = 0.05
    rib_thickness: float = 1.0
    distribution_pattern: str = "exp"
    liquid_port_diameter: float = 10.0
    port_inset_ratio: float = 0.125
    bolts_per_side: int = 3
    bolt_diameter: float = 6.3
    fillet_ratio: float = 0.04
    endplate_x_offset: float = 20.0
    endplate_y_offset: float = 20.0
    gasket_x_offset: float = 0.0
    gasket_y_offset: float = 0.0
    current_collector_x_offset: float = 0.0
    current_collector_y_offset: float = 0.0
    current_collector_tab_length: float = 50.0
    current_collector_tab_width: float = 30.0
    current_collector_tab_hole_radius: float = 4.15
    
    endplate_z: float = 12.0
    use_hose_barbs: bool = False
    barb_total_height: float = 20.0
    barb_inner_radius: float = 3.0
    barb_stem_radius: float = 4.5
    barb_outer_radius: float = 6.0
    barb_count: int = 3
    barb_base_fillet: float = 3.0

@app.post("/generate")
async def generate_cell(params: CellParameters):
    session_id = str(uuid.uuid4())
    temp_dir = f"/tmp/{session_id}"
    os.makedirs(temp_dir, exist_ok=True)

    gen = FlowCellGenerator(**params.dict())

    flow_frame = gen.generate_flow_frame()
    flow_field = gen.generate_flow_field()
    
    # 1. ALWAYS generate and export the flat end plate for the zip download
    end_plate_flat = gen.generate_end_plate(thickness=params.endplate_z)
    export_step(end_plate_flat, f"{temp_dir}/end_plate_flat.step")
    export_stl(end_plate_flat, f"{temp_dir}/end_plate_flat.stl")
    
    # 2. Handle the Barbed logic
    if params.use_hose_barbs:
        end_plate_barbed = gen.generate_end_plate_with_barbs(thickness=params.endplate_z)
        export_step(end_plate_barbed, f"{temp_dir}/end_plate_barbed.step")
        export_stl(end_plate_barbed, f"{temp_dir}/end_plate_barbed.stl")
        
        # Save a duplicate named "end_plate.stl" so the frontend viewer loads the barbed version
        export_stl(end_plate_barbed, f"{temp_dir}/end_plate.stl")
    else:
        # Save a duplicate named "end_plate.stl" so the frontend viewer loads the flat version
        export_stl(end_plate_flat, f"{temp_dir}/end_plate.stl")
        
    gasket_2d = gen.generate_gasket()
    endplate_cc_2d = gen.generate_current_collector()
    bipolar_cc_2d = gen.generate_bipolar_current_collector()
    end_plate_2d = gen.generate_end_plate_sketch()

    gasket_3d = extrude(gasket_2d, amount=1.0)
    endplate_cc_3d = extrude(endplate_cc_2d, amount=2.0)
    bipolar_cc_3d = extrude(bipolar_cc_2d, amount=3.0)

    # Export remaining STLs for the web viewer
    export_stl(endplate_cc_3d, f"{temp_dir}/endplate_cc.stl")
    export_stl(gasket_3d, f"{temp_dir}/gasket.stl")
    export_stl(flow_frame, f"{temp_dir}/flow_frame.stl")
    export_stl(bipolar_cc_3d, f"{temp_dir}/bipolar_cc.stl")

    # Export remaining STEPs for fluid simulation
    export_step(flow_frame, f"{temp_dir}/flow_frame.step")
    export_step(flow_field, f"{temp_dir}/flow_field_fluid_domain.step")

    # Export 2D DXFs for laser/waterjet cutting
    for part_2d, name in zip([gasket_2d, endplate_cc_2d, bipolar_cc_2d, end_plate_2d], 
                           ["gasket", "endplate_cc", "bipolar_cc", "end_plate"]):
        export_dxf = ExportDXF()
        export_dxf.add_shape(part_2d)
        export_dxf.write(f"{temp_dir}/{name}.dxf")

    return {
        "status": "success",
        "session_id": session_id,
        "files": ["end_plate.stl", "endplate_cc.stl", "gasket.stl", "flow_frame.stl", "bipolar_cc.stl"]
    }

@app.get("/download/{session_id}/{filename}")
async def download_file(session_id: str, filename: str):
    file_path = f"/tmp/{session_id}/{filename}"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}

@app.get("/download-zip/{session_id}")
async def download_zip(session_id: str):
    dir_path = f"/tmp/{session_id}"
    if not os.path.exists(dir_path):
        return {"error": "Session directory not found"}
    
    zip_base_path = f"/tmp/{session_id}_build_a_batt"
    shutil.make_archive(zip_base_path, 'zip', dir_path)
    return FileResponse(f"{zip_base_path}.zip", media_type="application/zip", filename="Build_a_Batt_Manufacturing_Files.zip")

@app.get("/")
async def root():
    return FileResponse("app/static/index.html")
