import math
import copy
import random
from shapely.geometry import Polygon
from shapely.affinity import translate, rotate
from shapely.ops import unary_union
from PySide import QtGui
import FreeCAD
from ....datatypes.sheet import Sheet
from ....datatypes.placed_part import PlacedPart

# --- Base Packer Class ---
class BaseNester(object):
    """Base class for nesting algorithms. Relies on the shapely library."""
    def __init__(self, width, height, rotation_steps=1, **kwargs):
        self._bin_width = width
        self._bin_height = height
        self.rotation_steps = rotation_steps if rotation_steps > 0 else 1
        self.spacing = kwargs.get("spacing", 0)
        self.max_spawn_count = kwargs.get("max_spawn_count", 100)
        self.anneal_steps = kwargs.get("anneal_steps", 100)
        self.step_size = kwargs.get("step_size", 5.0)
        self.anneal_rotate_enabled = kwargs.get("anneal_rotate_enabled", True)
        self.anneal_translate_enabled = kwargs.get("anneal_translate_enabled", True)
        self.anneal_random_shake_direction = kwargs.get("anneal_random_shake_direction", False)

        self.parts_to_place = [] # This list will hold Shape objects
        self.sheets = []
        
        self._bin_polygon = Polygon([(0, 0), (width, 0), (width, height), (0, height)])

    def _attempt_placement_on_sheet(self, part, sheet):
        """
        Attempts to place a part on a sheet, and if successful, finalizes
        its placement and adds it to the sheet.
        Returns True on success, False on failure.
        """
        placed_part_shape = self._try_place_part_on_sheet(part, sheet)
        
        # Final validation to ensure the returned part is valid before accepting it.
        if placed_part_shape and sheet.is_placement_valid(placed_part_shape, recalculate_union=False):
            sheet_origin = sheet.get_origin(self.spacing)
            placed_part_shape.placement = placed_part_shape.get_final_placement(sheet_origin)
            sheet.add_part(PlacedPart(placed_part_shape))
            return True
        elif placed_part_shape:
            FreeCAD.Console.PrintWarning(f"Nester algorithm returned an invalid placement for {part.id}. Discarding.\n")
        
        return False

    def nest(self, parts):
        """
        Main nesting loop. Iterates through parts and calls the subclass's
        sheet nesting implementation until all parts are placed or no more
        can be placed.
        """

        self.parts_to_place = list(parts)
        self.sheets = []
        self._sort_parts_by_area() # Sorts self.parts_to_place in-place
        unplaced_shapes = []

        while self.parts_to_place:
            original_shape = self.parts_to_place.pop(0) # Get and remove the largest remaining part
            placed = False
            
            # Try to place on existing sheets first
            for sheet in self.sheets:
                if self._attempt_placement_on_sheet(original_shape, sheet):
                    placed = True
                    break
            
            if not placed:
                # If it didn't fit on any existing sheet, try a new one
                new_sheet_id = len(self.sheets)
                new_sheet = Sheet(new_sheet_id, self._bin_width, self._bin_height) # Create a new sheet
                
                if self._attempt_placement_on_sheet(original_shape, new_sheet):
                    self.sheets.append(new_sheet)
                    placed = True
                else:
                    # If it can't even fit on an empty sheet, it's unplaceable
                    unplaced_shapes.append(original_shape)

        return self.sheets, unplaced_shapes


    def _sort_parts_by_area(self):
        """Sorts the list of parts to be nested in-place, largest area first."""
        self.parts_to_place.sort(key=lambda p: p.area, reverse=True)

    def _try_place_part_on_sheet(self, part_to_place, sheet):
        """
        Subclasses must implement this. Tries to place a single shape on a given sheet.
        Returns the placed shape on success, None on failure.
        """
        raise NotImplementedError

    def _anneal_part(self, part_to_shake, sheet, current_gravity_direction, rotate_enabled=True, translate_enabled=True):
        """
        Attempts to "anneal" a shape out of a collision by trying small
        perpendicular and/or rotational movements. This is a local search
        mechanism to find a valid spot when a part gets stuck.
        Returns a tuple of (position, rotation) on success. If it can't find
        a valid position, it returns the starting position and rotation.
        """

        start_centroid = part_to_shake.centroid
        start_pos = (start_centroid.x, start_centroid.y) if start_centroid else (0, 0)
        start_rot = part_to_shake.angle # This is the angle to return if shaking fails

        # If no annealing steps are configured or both rotate and translate are disabled, return immediately.
        if self.anneal_steps == 0 or (not self.anneal_rotate_enabled and not self.anneal_translate_enabled) or (not rotate_enabled and not translate_enabled):
            return start_pos, start_rot

        # Store the initial state of the part.
        initial_bl_x, initial_bl_y, _, _ = part_to_shake.bounding_box()
        initial_angle = part_to_shake.angle

        # Determine the base perpendicular direction (relative to the current gravity)
        base_perp_dir = (-current_gravity_direction[1], current_gravity_direction[0])

        # Randomize the initial side direction to avoid bias (e.g., always trying right first)
        # Randomize the initial side direction to avoid bias (e.g., always trying right first)
        initial_side_direction = random.choice([1, -1])
        for i in range(self.anneal_steps):
            amplitude = self.step_size * (i // 2 + 1)
            side_direction = initial_side_direction if i % 2 == 0 else -initial_side_direction

            # Reset the part to its initial state (before any shaking attempts in this loop)
            part_to_shake.move_to(initial_bl_x, initial_bl_y)
            part_to_shake.set_rotation(initial_angle) # Order matters: move then rotate
            
            # Apply rotation if enabled
            if self.anneal_rotate_enabled and rotate_enabled and part_to_shake.rotation_steps > 1:
                # Oscillate the rotation similar to translation
                angle_step_magnitude = (360.0 / part_to_shake.rotation_steps) * (i // 2 + 1)
                
                # Use the same side_direction logic for rotation oscillation
                rotation_direction = side_direction 

                new_angle = (initial_angle + angle_step_magnitude * rotation_direction) % 360.0
                part_to_shake.set_rotation(new_angle)

            # Determine the perpendicular direction for this specific anneal attempt
            perp_dir_for_shake = (0, 0) # Default to no movement
            if self.anneal_translate_enabled and translate_enabled:
                if self.anneal_random_shake_direction:
                    # Generate a completely random direction for this shake attempt
                    random_angle_rad = random.uniform(0, 2 * math.pi)
                    temp_gravity_dir = (math.cos(random_angle_rad), math.sin(random_angle_rad))
                    perp_dir_for_shake = (-temp_gravity_dir[1], temp_gravity_dir[0])
                else:
                    perp_dir_for_shake = base_perp_dir # Use the perpendicular to the current gravity direction

                shake_dx = perp_dir_for_shake[0] * amplitude * side_direction
                shake_dy = perp_dir_for_shake[1] * amplitude * side_direction
                part_to_shake.move(shake_dx, shake_dy)
            
            if sheet.is_placement_valid(part_to_shake, recalculate_union=False, part_to_ignore=part_to_shake):
                # Found a valid position. Return its current centroid and angle.
                new_centroid = part_to_shake.centroid
                new_pos = (new_centroid.x, new_centroid.y) if new_centroid else (0, 0)
                return new_pos, part_to_shake.angle
            # If invalid, the loop will continue, and the next iteration will reset the part.

        # If the loop finishes, no valid shake was found.
        # Revert the part to its original state before returning the initial position.
        part_to_shake.move_to(initial_bl_x, initial_bl_y)
        part_to_shake.set_rotation(initial_angle)

        return start_pos, start_rot # Could not shake free, return original state
    
    def _check_intersection(self, part1, part2):
        """Checks if two parts intersect."""
        if not part1.polygon or not part2.polygon:
            return False
        return part1.polygon.intersects(part2.polygon)

    def _get_overlap_area(self, part1, part2):
        """Calculates the overlapping area between two parts."""
        if not part1.polygon or not part2.polygon or not part1.polygon.intersects(part2.polygon):
            return 0.0
        try:
            return part1.polygon.intersection(part2.polygon).area
        except Exception:
            return 0.0 # Fallback if intersection fails

    def _get_outside_area(self, shape):
        """Calculates the area of a shape that is outside the bin."""
        if not shape.polygon or self._bin_polygon.contains(shape.polygon):
            return 0.0
        try:
            return shape.polygon.difference(self._bin_polygon).area
        except Exception:
            return 0.0 # Fallback if difference fails