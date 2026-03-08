import math
from typing import Tuple, List, Union, Literal
from build123d import *
from ocp_vscode import *

class FlowCellGenerator:
    """
    A parametric generator for flow battery cell components.
    
    This class consolidates geometry generation for flow frames, flow fields,
    end plates, gaskets, and current collectors using build123d.
    """

    def __init__(
        self,
        # Plate Dimensions
        plate_x: float = 200.0,
        plate_y: float = 200.0,
        plate_z_flow: float = 1.0, 
        
        # Active Area
        electrode_x: float = 130.0,
        electrode_y: float = 130.0,
        
        # Manifolds & Channels
        manifold_wall_thickness: float = 0.0,
        manifold_max_width: float = 15,
        manifold_min_width: float = 10.0,
        distribution_length: float = 0.0,
        distribution_growth_rate: float = 0.05,
        rib_thickness: float = 1.0,
        distribution_pattern: str = "exp",
        
        # Ports
        liquid_port_diameter: float = 10.0,
        port_inset_ratio: float = 0.125,
        
        # Mechanical (Bolts)
        bolts_per_side: int = 3,
        bolt_diameter: float = 6.3,
        
        # Fabrication
        fillet_ratio: float = 0.04,

        # Offsets & Hardware Parameters
        endplate_x_offset: float = 20.0,
        endplate_y_offset: float = 20.0,
        gasket_x_offset: float = 0.0,
        gasket_y_offset: float = 0.0,
        current_collector_x_offset: float = 0.0,
        current_collector_y_offset: float = 0.0,
        current_collector_tab_length: float = 50.0,
        current_collector_tab_width: float = 30.0,
        current_collector_tab_hole_radius: float = 4.15
    ):
        # Store parameters
        self.plate_x = plate_x
        self.plate_y = plate_y
        self.plate_z_flow = plate_z_flow
        self.electrode_x = electrode_x
        self.electrode_y = electrode_y
        
        self.manifold_wall_thickness = manifold_wall_thickness
        self.manifold_channel_depth = plate_z_flow - (manifold_wall_thickness * 2)
        self.manifold_max_width = manifold_max_width
        self.manifold_min_width = manifold_min_width
        
        self.dist_len = distribution_length
        self.dist_rate = distribution_growth_rate
        self.rib_thickness = rib_thickness
        self.dist_pattern = distribution_pattern
        
        self.port_dia = liquid_port_diameter
        self.port_radius = liquid_port_diameter / 2
        self.port_inset = port_inset_ratio
        
        self.bolts_per_side = bolts_per_side
        self.bolt_dia = bolt_diameter
        self.fillet_ratio = fillet_ratio

        # Offsets
        self.endplate_x_offset = endplate_x_offset
        self.endplate_y_offset = endplate_y_offset
        self.gasket_x_offset = gasket_x_offset
        self.gasket_y_offset = gasket_y_offset
        self.cc_x_offset = current_collector_x_offset
        self.cc_y_offset = current_collector_y_offset
        self.cc_tab_length = current_collector_tab_length
        self.cc_tab_width = current_collector_tab_width
        self.cc_tab_hole_radius = current_collector_tab_hole_radius

        # Derived coordinates (calculated once)
        self.inlet_coords = (plate_x * self.port_inset, plate_y * self.port_inset)
        self.outlet_coords = (plate_x * (1 - self.port_inset), plate_y * (1 - self.port_inset))
        self.dummy_coords = [
            (plate_x * self.port_inset, plate_y * (1 - self.port_inset)),
            (plate_x * (1 - self.port_inset), plate_y * self.port_inset)
        ]

    # ==========================================================================
    # HELPER METHODS (Static)
    # ==========================================================================

    @staticmethod
    def _get_tangent_points(circle_center, radius, target_point):
        cx, cy = circle_center
        px, py = target_point
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy)
        
        if dist < radius: 
            raise ValueError("Target point is inside the circle")

        angle_to_p = math.atan2(dy, dx)
        offset_angle = math.acos(radius / dist)
        
        p1 = (cx + radius * math.cos(angle_to_p + offset_angle), cy + radius * math.sin(angle_to_p + offset_angle))
        p2 = (cx + radius * math.cos(angle_to_p - offset_angle), cy + radius * math.sin(angle_to_p - offset_angle))
        return p1, p2

    @staticmethod
    def _layout_rectangles(Ltotal, rect_width, growth="exp", rate=0.2, lead_margin=None, trail_margin=None, min_first_gap=2, max_gap=None):
        if lead_margin is None or trail_margin is None:
            lead_margin = rect_width * 2
            trail_margin = -rect_width * 3

        Luse = Ltotal - lead_margin - trail_margin
        if Luse <= 0 or rect_width <= 0: 
            return [], 0, 0.0, []
        
        def f(i):
            if growth == "exp": return (1.0 + rate)**i
            elif growth == "arith": return 1.0 + rate * i
            elif growth == "power": return float(i+1)**rate
            else: raise ValueError

        def calculate_sum_weights(num_gaps):
            if num_gaps <= 0: return 0.0
            if growth == "exp":
                r = 1.0 + rate
                if abs(r - 1.0) < 1e-12: return float(num_gaps)
                return (1.0 - r**num_gaps) / (1.0 - r)
            elif growth == "arith":
                return (num_gaps / 2.0) * (2.0 + (num_gaps - 1) * rate)
            return sum(f(i) for i in range(num_gaps))

        N_theoretical_max = int(Luse // rect_width)
        bestN = 0
        best_s0 = 0.0
        
        for N in range(N_theoretical_max, 1, -1):
            num_gaps = N - 1
            length_solids = N * rect_width
            length_fluid = Luse - length_solids
            if length_fluid <= 0: continue
            total_weight = calculate_sum_weights(num_gaps)
            if total_weight <= 0: continue
            s0 = length_fluid / total_weight
            s_last = s0 * f(num_gaps - 1)

            actual_min_gap = min(s0, s_last)
            actual_max_gap = max(s0, s_last)

            if actual_min_gap >= min_first_gap:
                if max_gap is not None and actual_max_gap > max_gap:
                    continue 
                bestN = N
                best_s0 = s0
                break

        if bestN == 0: return [], 0, 0.0, []

        gaps = [best_s0 * f(i) for i in range(bestN - 1)]
        positions = []
        x = lead_margin
        for j in range(bestN):
            positions.append(x)
            x += rect_width
            if j < bestN - 1:
                x += gaps[j]
                
        return positions, bestN, best_s0, gaps

    # ==========================================================================
    # INTERNAL BUILDERS
    # ==========================================================================

    def _build_bolt_locations(self) -> List[Tuple[float, float]]:
        """Generates coordinate list for perimeter bolts."""
        boltX = [self.plate_x / (self.bolts_per_side + 1) * i for i in range(1, self.bolts_per_side + 1)]
        boltY = [self.plate_y / (self.bolts_per_side + 1) * i for i in range(1, self.bolts_per_side + 1)]
        return (
            [(x, 0) for x in boltX] + 
            [(x, self.plate_y) for x in boltX] + 
            [(0, y) for y in boltY] + 
            [(self.plate_x, y) for y in boltY]
        )

    def _build_channels_sketch(self) -> Sketch:
        """Generates the flow distribution channels and manifold shapes."""
        aa_x_min = (self.plate_x - self.electrode_x) / 2
        aa_x_max = aa_x_min + self.electrode_x
        aa_y_min = (self.plate_y - self.electrode_y) / 2
        aa_y_max = aa_y_min + self.electrode_y

        dist_inlet_y = aa_y_min - self.dist_len
        dist_outlet_y = aa_y_max + self.dist_len

        _, _, _, gaps_ascending = self._layout_rectangles(
            self.electrode_x, rect_width=self.rib_thickness, 
            growth=self.dist_pattern, rate=self.dist_rate
        )
        gaps_descending = list(reversed(gaps_ascending))

        with BuildSketch() as sketch:
            # 1. Inlet Fingers (Bottom)
            current_x = aa_x_min
            finger_h = (aa_y_min + 1.0) - dist_inlet_y
            finger_cy = dist_inlet_y + finger_h/2
            for width in gaps_ascending:
                current_x += self.rib_thickness
                cx = current_x + width/2
                with Locations((cx, finger_cy)):
                    Rectangle(width, finger_h)
                current_x += width

            # 2. Outlet Fingers (Top)
            current_x = aa_x_min
            finger_h = dist_outlet_y - (aa_y_max - 1.0)
            finger_cy = dist_outlet_y - finger_h/2
            for width in gaps_descending:
                current_x += self.rib_thickness
                cx = current_x + width/2
                with Locations((cx, finger_cy)):
                    Rectangle(width, finger_h)
                current_x += width

            # 3. Inlet Manifold
            in_tl, in_tr = (aa_x_min, dist_inlet_y), (aa_x_max, dist_inlet_y)
            in_br, in_bl = (aa_x_max, dist_inlet_y - self.manifold_min_width), (aa_x_min, dist_inlet_y - self.manifold_max_width)
            
            with BuildLine(): Polyline([in_tl, in_tr, in_br, in_bl, in_tl])
            make_face()
            
            t_upper, _ = self._get_tangent_points(self.inlet_coords, self.port_radius, in_tl)
            _, t_lower = self._get_tangent_points(self.inlet_coords, self.port_radius, in_bl)
            with BuildLine(): 
                Polyline([t_upper, in_tl, in_bl, t_lower])
                Polyline([t_lower, self.inlet_coords, t_upper])
            make_face()

            # 4. Outlet Manifold
            out_bl, out_br = (aa_x_min, dist_outlet_y), (aa_x_max, dist_outlet_y)
            out_tr, out_tl = (aa_x_max, dist_outlet_y + self.manifold_max_width), (aa_x_min, dist_outlet_y + self.manifold_min_width)

            with BuildLine(): Polyline([out_bl, out_br, out_tr, out_tl, out_bl])
            make_face()

            t_lower, _ = self._get_tangent_points(self.outlet_coords, self.port_radius, out_br)
            _, t_upper = self._get_tangent_points(self.outlet_coords, self.port_radius, out_tr)
            with BuildLine():
                Polyline([t_lower, out_br, out_tr, t_upper])
                Polyline([t_upper, self.outlet_coords, t_lower])
            make_face()
            
        return sketch.sketch

    # ==========================================================================
    # GEOMETRY GENERATORS
    # ==========================================================================

    def generate_flow_frame(self) -> Part:
        """
        Generates the Flow Frame (Open Center, patterned manifold design).
        """
        plate_fillet = min(self.plate_x, self.plate_y) * self.fillet_ratio
        with BuildSketch() as base_rect:
            Rectangle(self.plate_x, self.plate_y, align=(Align.MIN, Align.MIN))
            fillet(base_rect.vertices(), radius=plate_fillet)

        with BuildSketch() as through_holes:
            with Locations(self._build_bolt_locations()):
                Circle(self.bolt_dia / 2)
            with Locations(self.dummy_coords + [self.inlet_coords, self.outlet_coords]):
                Circle(self.port_dia / 2)
            with Locations((self.plate_x/2, self.plate_y/2)):
                Rectangle(self.electrode_x, self.electrode_y)

        channel_sketch = self._build_channels_sketch()

        with BuildPart() as part:
            if self.manifold_wall_thickness > 0:
                extrude(base_rect.sketch, amount=self.plate_z_flow - self.manifold_wall_thickness)
                extrude(channel_sketch, amount=self.manifold_channel_depth, mode=Mode.SUBTRACT)
                extrude(base_rect.sketch, amount=-self.manifold_wall_thickness)
            else:
                extrude(base_rect.sketch, amount=self.plate_z_flow)
                extrude(channel_sketch, amount=self.plate_z_flow, mode=Mode.SUBTRACT)
            
            with Locations((0,0,0)):
                extrude(through_holes.sketch, amount=self.plate_z_flow, both=True, mode=Mode.SUBTRACT)
        
        part.label = "FlowFrame"
        return part.part

    def generate_bipolar_current_collector(self) -> Sketch:
        """
        Generates a 2D Bipolar Current Collector profile.
        """
        plate_fillet = min(self.plate_x, self.plate_y) * self.fillet_ratio
        
        with BuildSketch() as sketch:
            with Locations((self.plate_x/2, self.plate_y/2)):
                Rectangle(self.plate_x, self.plate_y)
            fillet(sketch.vertices(), radius=plate_fillet)
            
            with BuildSketch(mode=Mode.SUBTRACT):
                with Locations(self._build_bolt_locations()):
                    Circle(self.bolt_dia / 2)
                with Locations(self.dummy_coords + [self.inlet_coords, self.outlet_coords]):
                    Circle(self.port_dia / 2)
        
        return sketch.sketch

    def generate_flow_field(self) -> Part:
        """
        Generates the Flow Field (negative of the Flow Frame).
        """
        channel_sketch = self._build_channels_sketch()

        with BuildSketch() as wetted_areas:
            with Locations([self.inlet_coords, self.outlet_coords]):
                Circle(self.port_dia / 2)
            with Locations((self.plate_x/2, self.plate_y/2)):
                Rectangle(self.electrode_x, self.electrode_y)

        with BuildPart() as part:
            extrude(channel_sketch, amount=self.manifold_channel_depth)
            extrude(
                wetted_areas.sketch.moved(Location((0, 0, -self.manifold_wall_thickness))), 
                amount=self.plate_z_flow
            )

        part.label = "FlowField_FluidDomain"
        return part.part

    def generate_end_plate_sketch(self) -> Sketch:
        """
        Script 3 (2D Component): Generates the profile for the structural end plate. 
        """
        fillet_r = min(self.plate_x + self.endplate_x_offset, self.plate_y + self.endplate_y_offset) * self.fillet_ratio
        
        with BuildSketch() as sketch:
            with Locations((self.plate_x/2, self.plate_y/2)):
                Rectangle(self.plate_x + self.endplate_x_offset, self.plate_y + self.endplate_y_offset)
            fillet(sketch.vertices(), radius=fillet_r)
            
            with BuildSketch(mode=Mode.SUBTRACT):
                with Locations(self._build_bolt_locations()):
                    Circle(self.bolt_dia / 2)
                with Locations(self.dummy_coords + [self.inlet_coords, self.outlet_coords]):
                    Circle(self.port_dia / 2)
        
        return sketch.sketch

    def generate_end_plate(self, thickness=12.0) -> Part:
        """
        Script 3 (3D Component): Generates the structural End Plate.
        """
        profile = self.generate_end_plate_sketch()
        with BuildPart() as part:
            extrude(profile, amount=thickness)
        
        part.label = "EndPlate"
        return part.part

    def generate_gasket(self) -> Sketch:
        """
        Script 4: Generates the Gasket cutout profile.
        """
        fillet_r = min(self.plate_x + self.gasket_x_offset, self.plate_y + self.gasket_y_offset) * self.fillet_ratio
        
        with BuildSketch() as sketch:
            with Locations((self.plate_x/2, self.plate_y/2)):
                Rectangle(self.plate_x + self.gasket_x_offset, self.plate_y + self.gasket_y_offset)
            fillet(sketch.vertices(), radius=fillet_r)
            
            with BuildSketch(mode=Mode.SUBTRACT):
                with Locations(self._build_bolt_locations()):
                    Circle(self.bolt_dia / 2)
                with Locations(self.dummy_coords + [self.inlet_coords, self.outlet_coords]):
                    Circle(self.port_dia / 2)
                with Locations((self.plate_x/2, self.plate_y/2)):
                    Rectangle(self.electrode_x, self.electrode_y)
                    
        return sketch.sketch

    def generate_current_collector(self) -> Sketch:
        """
        Script 5/6: Generates the endplate Current Collector/Busbar profile.
        """
        fillet_r = min(self.plate_x + self.cc_x_offset, self.plate_y + self.cc_y_offset) * self.fillet_ratio
        tab_offset_y = self.plate_y / (self.bolts_per_side + 1)
        
        # Derived Centers
        base_cx, base_cy = self.plate_x/2, self.plate_y/2
        tab_cx = (self.plate_x + self.cc_x_offset/2) + self.cc_tab_length/2
        tab_cy = base_cy + tab_offset_y
        
        with BuildSketch() as sketch:
            # 1. Main Body + Tab (Fused)
            with Locations((base_cx, base_cy)):
                Rectangle(self.plate_x + self.cc_x_offset, self.plate_y + self.cc_y_offset)
            with Locations((tab_cx, tab_cy)):
                Rectangle(self.cc_tab_length, self.cc_tab_width)
            
            # Fillet outer corners
            fillet(sketch.vertices(), radius=fillet_r)
            
            # 2. Cutouts
            with BuildSketch(mode=Mode.SUBTRACT):
                with Locations(self._build_bolt_locations()):
                    Circle(self.bolt_dia / 2)
                with Locations(self.dummy_coords + [self.inlet_coords, self.outlet_coords]):
                    Circle(self.port_dia / 2)
                with Locations((tab_cx, tab_cy)):
                    Circle(self.cc_tab_hole_radius)
        
        return sketch.sketch