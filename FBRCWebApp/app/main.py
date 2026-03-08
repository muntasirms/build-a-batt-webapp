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

@app.post("/generate")
async def generate_cell(params: CellParameters):
    session_id = str(uuid.uuid4())
    temp_dir = f"/tmp/{session_id}"
    os.makedirs(temp_dir, exist_ok=True)

    gen = FlowCellGenerator(**params.dict())

    # 1. Generate Base Parts
    flow_frame = gen.generate_flow_frame()
    flow_field = gen.generate_flow_field() # Crucial for CFD STEP export
    end_plate = gen.generate_end_plate(thickness=10.0)
    
    gasket_2d = gen.generate_gasket()
    endplate_cc_2d = gen.generate_current_collector()
    bipolar_cc_2d = gen.generate_bipolar_current_collector()
    end_plate_2d = gen.generate_end_plate_sketch()

    # 2. Extrude 2D sketches for the 3D web viewer
    gasket_3d = extrude(gasket_2d, amount=1.0)
    endplate_cc_3d = extrude(endplate_cc_2d, amount=2.0)
    bipolar_cc_3d = extrude(bipolar_cc_2d, amount=3.0)

    # 3. Export STLs (Used by web viewer and for 3D printing)
    export_stl(end_plate, f"{temp_dir}/end_plate.stl")
    export_stl(endplate_cc_3d, f"{temp_dir}/endplate_cc.stl")
    export_stl(gasket_3d, f"{temp_dir}/gasket.stl")
    export_stl(flow_frame, f"{temp_dir}/flow_frame.stl")
    export_stl(bipolar_cc_3d, f"{temp_dir}/bipolar_cc.stl")

    # 4. Export STEPs (For CNC milling and CFD Simulation)
    export_step(flow_frame, f"{temp_dir}/flow_frame.step")
    export_step(flow_field, f"{temp_dir}/flow_field_fluid_domain.step")
    export_step(end_plate, f"{temp_dir}/end_plate.step")

    # 5. Export DXFs (For Laser / Waterjet cutting)
    

    for part_2d, name in zip([gasket_2d, endplate_cc_2d, bipolar_cc_2d, end_plate_2d], 
                           ["gasket", "endplate_cc", "bipolar_cc", "end_plate"]):
        export_dxf = ExportDXF()
        export_dxf.add_shape(part_2d)
        export_dxf.write(f"{temp_dir}/{name}.dxf")

    
    # export_dxf(gasket_2d, f"{temp_dir}/gasket.dxf")
    # export_dxf(endplate_cc_2d, f"{temp_dir}/endplate_cc.dxf")
    # export_dxf(bipolar_cc_2d, f"{temp_dir}/bipolar_cc.dxf")
    # export_dxf(end_plate_2d, f"{temp_dir}/end_plate.dxf")

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
    """Zips the entire session directory and returns it to the user."""
    dir_path = f"/tmp/{session_id}"
    if not os.path.exists(dir_path):
        return {"error": "Session directory not found"}
    
    zip_base_path = f"/tmp/{session_id}_build_a_batt"
    # Create a zip archive of the directory
    shutil.make_archive(zip_base_path, 'zip', dir_path)
    
    return FileResponse(
        f"{zip_base_path}.zip", 
        media_type="application/zip", 
        filename="Build_a_Batt_Manufacturing_Files.zip"
    )

@app.get("/")
async def root():
    return FileResponse("app/static/index.html")