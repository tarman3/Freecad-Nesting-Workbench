
import math
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from shapely.geometry import Polygon, MultiPolygon, Point, MultiPoint
from shapely.affinity import translate, rotate
from shapely.ops import unary_union
from . import minkowski_utils
from ....datatypes.shape import Shape

class MinkowskiEngine:
    """
    Handles geometric operations for Minkowski nesting, such as NFP generation,
    candidate point finding, and placement validation.
    """
    def __init__(self, bin_width, bin_height, step_size, discretize_edges=True, log_callback=None):
        self.bin_width = bin_width
        self.bin_height = bin_height
        self.step_size = step_size
        self.discretize_edges = discretize_edges
        self.log_callback = log_callback
        self._log_lock = Lock()
        self.bin_polygon = Polygon([(0, 0), (self.bin_width, 0), (self.bin_width, self.bin_height), (0, self.bin_height)])

    def log(self, message):
        if self.log_callback:
            with self._log_lock:
                self.log_callback("MINKOWSKI_ENGINE: " + message)
        else:
             # Fallback to FreeCAD console if no callback is wired
             import FreeCAD
             FreeCAD.Console.PrintMessage(f"MINKOWSKI_ENGINE: {message}\n")

    def is_placement_valid_with_holes(self, polygon_to_check, sheet, union_of_other_parts):
        """
        Custom validation function for Minkowski that correctly handles holes.
        """
        # 1. Check containment within sheet boundaries
        if not self.bin_polygon.contains(polygon_to_check):
            return False

        # 2. Check against the pre-calculated union of other parts
        if not union_of_other_parts:
            return True # No other parts to collide with

        # --- Advanced Collision Check with Hole Support ---
        if not polygon_to_check.intersects(union_of_other_parts):
            return True # No intersection at all, definitely valid.

        # There is an intersection. Check if it's a valid placement inside a hole.
        intersection_area = polygon_to_check.intersection(union_of_other_parts).area
        if intersection_area < 1e-9:
            return True # Negligible intersection is likely just touching, which is allowed.

        # The placement is only valid if the part is entirely contained within one of the holes.
        if union_of_other_parts.geom_type == 'Polygon':
            return any(hole.contains(polygon_to_check) for hole in union_of_other_parts.interiors)
        elif union_of_other_parts.geom_type == 'MultiPolygon':
            return any(
                hole.contains(polygon_to_check)
                for poly in union_of_other_parts.geoms
                for hole in poly.interiors
            )
        return False

    def get_candidate_positions(self, nfps, part_to_place_poly=None):
        """
        Generates candidate placement points from the vertices of the No-Fit Polygon.
        """
        external_points = []
        hole_points = []

        # Add the sheet origin as a primary external candidate.
        if part_to_place_poly:
            min_x, min_y, max_x, max_y = part_to_place_poly.bounds
            
            # 1. Bottom-Left: Part's min_x, min_y at 0,0
            external_points.append(Point(-min_x, -min_y))
            
            w_bin = self.bin_width
            h_bin = self.bin_height
            
            external_points.append(Point(w_bin - max_x, -min_y)) # Bottom-Right
            external_points.append(Point(-min_x, h_bin - max_y)) # Top-Left
            external_points.append(Point(w_bin - max_x, h_bin - max_y)) # Top-Right

        for nfp_data in nfps:
            external_points.extend(nfp_data["exterior_points"])
            for interior_points in nfp_data["interior_points"]:
                hole_points.extend(interior_points)

        # Pre-filter candidate points
        unique_externals = list(MultiPoint(external_points).geoms)
        valid_external_candidates = []
        for p in unique_externals:
            if 0 <= p.x <= self.bin_width and 0 <= p.y <= self.bin_height:
                valid_external_candidates.append(p)

        unique_holes = list(MultiPoint(hole_points).geoms)
        valid_hole_candidates = []
        for p in unique_holes:
            if 0 <= p.x <= self.bin_width and 0 <= p.y <= self.bin_height:
                valid_hole_candidates.append(p)

        return valid_hole_candidates, valid_external_candidates

    def generate_nfps(self, part_to_place, placed_parts_grouped, angle):
        """
        Generates the No-Fit Polygons for a given part and existing placed parts.
        Returns a structure optimized for "Reference Frame" checking.
        """
        results = []
        part_to_place_master_label = part_to_place.source_freecad_object.Label

        for (placed_label, placed_angle), parts in placed_parts_grouped.items():
            
            # Normalize angles
            relative_angle = (angle - placed_angle) % 360.0
            relative_angle = round(relative_angle, 4)
            
            cache_key = (
                placed_label, 
                part_to_place_master_label, 
                relative_angle, 
                part_to_place.spacing,
                part_to_place.resolution
            )
            
            # 1. Retrieve or Calculate NFP
            nfp_data = Shape.nfp_cache.get(cache_key)
            if not nfp_data:
                first_part = parts[0]
                nfp_data = self._calculate_and_cache_nfp(
                    first_part.shape, 
                    0.0, 
                    part_to_place, 
                    relative_angle, 
                    cache_key
                )
            
            if not nfp_data:
                continue

            # 2. Prepare Group Data using Vectorized Operations
            # We rotate the Master NFP *once* for this entire group.
            master_nfp = nfp_data["polygon"]
            rotated_master_nfp = rotate(master_nfp, placed_angle, origin=(0, 0))
            
            # Extract offsets for all parts in this group
            # All parts in this group have the same rotation, so we only need their translations.
            offsets = []
            for p in parts:
                c = p.shape.centroid
                offsets.append((c.x, c.y))
            
            # 3. Generate Candidate Points (Absolute Coordinates)
            # We need to generate absolute candidate points for the solver.
            # We can do this efficiently by transforming the base points once per group offset.
            
            # Rotate points once
            ext_mp = MultiPoint(nfp_data["exterior_points"])
            rotated_ext = rotate(ext_mp, placed_angle, origin=(0, 0))
            
            int_mps = [rotate(MultiPoint(pts), placed_angle, origin=(0, 0)) for pts in nfp_data["interior_points"]]

            group_exterior_points = []
            group_interior_points = []

            # Bulk translate for each offset
            # This is still O(N*Points), but avoids Shapely object creation overhead for every point/polygon
            # We manually apply offset to coordinates which is faster than affinity.translate on geometry
            
            # Extract coords once
            r_ext_coords = [(p.x, p.y) for p in rotated_ext.geoms]
            r_int_coords_list = [[(p.x, p.y) for p in imp.geoms] for imp in int_mps]

            for off_x, off_y in offsets:
                group_exterior_points.extend([Point(x + off_x, y + off_y) for x, y in r_ext_coords])
                for r_int_coords in r_int_coords_list:
                     group_interior_points.append([Point(x + off_x, y + off_y) for x, y in r_int_coords])

            results.append({
                "polygon": rotated_master_nfp, # The NFP geometry rotated but NOT translated (centered at 0,0 relative to placement)
                "offsets": offsets,            # usage: check contains(pt - offset)
                "exterior_points": group_exterior_points,
                "interior_points": group_interior_points,
            })
                
        return results

    def get_global_nfp_for(self, part_to_place, angle, sheet):
        """
        Calculates (incrementally) the total forbidden area (Union of NFPs) 
        for a specific part rotation on the sheet.
        Returns dict with 'polygon', 'prepared', and candidate 'points'.
        """
        cache_key = (part_to_place.source_freecad_object.Label, round(angle, 4))
        
        # Initialize or Retrieve cache entry
        if cache_key not in sheet.nfp_cache:
            sheet.nfp_cache[cache_key] = {
                'polygon': Polygon(), # Start empty
                'last_part_idx': 0,
                'points': [],
                'prepared': None
            }
            
        entry = sheet.nfp_cache[cache_key]
        
        # If we are up to date, return immediately
        if entry['last_part_idx'] >= len(sheet.parts):
            return entry

        # We have new parts to process
        new_polys = []
        part_to_place_master_label = part_to_place.source_freecad_object.Label
        
        # Identify new parts
        parts_to_process = sheet.parts[entry['last_part_idx']:]
        
        for p in parts_to_process:
            placed_label = p.shape.source_freecad_object.Label
            placed_angle = p.angle
            
            # Normalize angle
            relative_angle = (angle - placed_angle) % 360.0
            relative_angle = round(relative_angle, 4)
            
            nfp_cache_key = (
                placed_label, 
                part_to_place_master_label, 
                relative_angle, 
                part_to_place.spacing,
                part_to_place.resolution
            )
            
            # Get Master NFP
            nfp_data = Shape.nfp_cache.get(nfp_cache_key)
            if not nfp_data:
                # Calculate if missing (synchronous)
                nfp_data = self._calculate_and_cache_nfp(
                    p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                )
            
            if nfp_data and nfp_data['polygon']:
                # Transform to sheet absolute position
                master = nfp_data['polygon']
                # Rotate
                rotated = rotate(master, placed_angle, origin=(0, 0))
                # Translate
                cent = p.shape.centroid
                translated = translate(rotated, xoff=cent.x, yoff=cent.y)
                new_polys.append(translated)
        
        # Update Union
        if new_polys:
            # Union all new usage areas
            batch_union = unary_union(new_polys)
            
            # Union with existing total
            if entry['polygon'].is_empty:
                entry['polygon'] = batch_union
            else:
                entry['polygon'] = entry['polygon'].union(batch_union)
                
            # Update derived data
            # Discretize the *Resulting Union* for clean candidate generation
            # This is much fewer points than discretizing every part!
            points = []
            if not entry['polygon'].is_empty:
                polys = [entry['polygon']] if entry['polygon'].geom_type == 'Polygon' else entry['polygon'].geoms
                for poly in polys:
                     # Exterior
                     points.extend(self._discretize_edge(poly.exterior))
                     # Holes
                     for interior in poly.interiors:
                         points.extend(self._discretize_edge(interior))
            
            entry['points'] = points
            entry['prepared'] = None # Invalidate prepared cache as polygon changed
            
            # Re-prepare for fast checking
            # entry['prepared'] = prep(entry['polygon']) # 'prep' not imported? 
            # We will prep in base_nester or import it here. 
            # Ideally we return raw poly and let base_nester prep. 
            # But user asked for caching on sheet. We can cache the raw poly.
        
        entry['last_part_idx'] = len(sheet.parts)
        return entry



    def _calculate_and_cache_nfp(self, shape_A, angle_A, part_to_place, angle_B, cache_key):
        with Shape.nfp_cache_lock:
            cached_nfp_data = Shape.nfp_cache.get(cache_key)
            if cached_nfp_data:
                return cached_nfp_data

        poly_A_master = shape_A.original_polygon
        poly_B_master = part_to_place.original_polygon
        
        # Center the master polygons to (0,0) for pure relative NFP calculation
        # This removes any inherent offset in the FreeCAD shape data
        cA = poly_A_master.centroid
        cB = poly_B_master.centroid
        
        poly_A_centered = translate(poly_A_master, -cA.x, -cA.y)
        poly_B_centered = translate(poly_B_master, -cB.x, -cB.y)
        
        # Calculate NFP using centered polygons
        # Target angle_A is usually 0.0 in this context (relative frame)
        nfp_exterior = minkowski_utils.minkowski_sum(
            poly_A_centered, angle_A, False, 
            poly_B_centered, angle_B, True, 
            self.log
        )
        
        nfp_interiors = []
        if poly_A_centered and poly_A_centered.interiors:
            # For holes, B is rotated around its (now 0,0) centroid
            poly_B_rotated = rotate(poly_B_centered, angle_B, origin=(0,0))
            
            for hole in poly_A_centered.interiors:
                # Holes are also centered relative to A's centroid
                hole_poly = Polygon(hole.coords)
                # No need to unrotate/rotate around centroid if angle_A is 0, but effectively:
                hole_poly_rotated = rotate(hole_poly, angle_A, origin=(0,0))
                
                # Check bounds optimization
                if (poly_B_rotated.bounds[2] - poly_B_rotated.bounds[0] < hole_poly_rotated.bounds[2] - hole_poly_rotated.bounds[0] and
                    poly_B_rotated.bounds[3] - poly_B_rotated.bounds[1] < hole_poly_rotated.bounds[3] - hole_poly_rotated.bounds[1] and
                        poly_B_rotated.area < hole_poly_rotated.area):
                    
                    ifp_raw = minkowski_utils.minkowski_difference(hole_poly_rotated, 0, poly_B_centered, angle_B, self.log)
                    
                    if ifp_raw and ifp_raw.area > 0:
                        if ifp_raw.geom_type == 'Polygon':
                            nfp_interiors.append(ifp_raw.exterior)
                        elif ifp_raw.geom_type == 'MultiPolygon':
                            for p in ifp_raw.geoms:
                                nfp_interiors.append(p.exterior)
        
        master_nfp = Polygon(nfp_exterior.exterior, nfp_interiors) if nfp_exterior and nfp_exterior.area > 0 else None
        
        nfp_data = None
        if master_nfp:
            nfp_data = {"polygon": master_nfp}
            if self.discretize_edges:
                nfp_data["exterior_points"] = self._discretize_edge(master_nfp.exterior)
                nfp_data["interior_points"] = [self._discretize_edge(interior) for interior in master_nfp.interiors]
            else:
                nfp_data["exterior_points"] = [Point(x, y) for x, y in master_nfp.exterior.coords]
                nfp_data["interior_points"] = [[Point(x, y) for x, y in interior.coords] for interior in master_nfp.interiors]
 
        with Shape.nfp_cache_lock:
            Shape.nfp_cache[cache_key] = nfp_data
        
        return nfp_data

    def _discretize_edge(self, line):
        points = [Point(line.coords[0])]
        length = line.length
        if length > self.step_size:
            num_segments = int(length / self.step_size)
            for i in range(1, num_segments):
                points.append(line.interpolate(float(i) / num_segments, normalized=True))
        points.append(Point(line.coords[-1]))
        return points
