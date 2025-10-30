import random
import math
#import pdb
import FreeCAD
from .base_nester import BaseNester

class GravityNester(BaseNester):
    """
    A packer that uses a simple physics-inspired "gravity" simulation.
    Parts are spawned at a random location and then moved in a specified
    direction until they collide with the sheet edge or another part.
    """

    def __init__(self, width, height, rotation_steps=1, **kwargs):
        super().__init__(width, height, rotation_steps, **kwargs)
        # --- Algorithm-specific parameters ---
        self.gravity_direction = kwargs.get("gravity_direction", (0, -1))
        self.max_spawn_count = kwargs.get("max_spawn_count", 100)
        self.max_nesting_steps = kwargs.get("max_nesting_steps", 500)

    def _spawn_part_on_sheet(self, shape, sheet):
        """
        Tries to place a shape at a random location without initial collision.
        Returns the spawned shape on success, or None on failure.
        """
        for _ in range(self.max_spawn_count):
            # The controller sets the definitive rotation_steps on the shape.
            if shape.rotation_steps > 1:
                angle = random.randrange(shape.rotation_steps) * (360 / shape.rotation_steps)
                shape.set_rotation(angle)

            _, _, w, h = shape.bounding_box()
            
            max_target_x = self._bin_width - w
            max_target_y = self._bin_height - h
            target_x = random.uniform(0, max_target_x) if max_target_x > 0 else 0
            target_y = random.uniform(0, max_target_y) if max_target_y > 0 else 0
            shape.move_to(target_x, target_y)

            if sheet.is_placement_valid(shape):
                return shape
        return None

    def _try_place_part_on_sheet(self, part_to_place, sheet):
        """
        Tries to place a single part on the given sheet using gravity simulation.
        Returns the placed part on success, None on failure.
        """
        spawned_part = self._spawn_part_on_sheet(part_to_place, sheet)
        
        if spawned_part:
            if self.gravity_direction is None: # None indicates random direction
                angle_rad = random.uniform(0, 2 * math.pi)
                part_direction = (math.cos(angle_rad), math.sin(angle_rad))
            else:
                part_direction = self.gravity_direction
            
            # The spawned part is now moved until it collides with something.
            return self._move_until_collision(spawned_part, sheet, part_direction)
        else:
            return None

    def _apply_gravity_to_part(self, part, sheet, direction):
        """Helper to move a part in a given direction until it collides."""
        # FreeCAD.Console.PrintMessage(f"DEBUG: Gravity: Moving part '{part.id}' (id={id(part)}). fc_object is {'set' if part.fc_object else 'None'}.\n")
        for _ in range(self.max_nesting_steps):
            # Record the last valid position's bottom-left corner
            last_valid_x, last_valid_y, _, _ = part.bounding_box()
            part.move(direction[0] * self.step_size, direction[1] * self.step_size)
            if self.update_callback:
                self.update_callback(part, sheet) # Force UI update for simulation
            
            if not sheet.is_placement_valid(part, recalculate_union=False, part_to_ignore=part):
                # Collision detected. Revert to the last valid position.
                part.move_to(last_valid_x, last_valid_y)
                break # Part has stopped moving.

    def _move_until_collision(self, part, sheet, direction):
        """
        Moves a part in the gravity direction step-by-step until it hits
        the bin edge or another placed part.
        If a collision occurs, it attempts to "shake" the part free once.
        """
        FreeCAD.Console.PrintMessage(f"\n--- Processing part {part.id} ---\n")
        # Loop to allow the part to repeatedly fall and shake until it settles.
        for i in range(self.max_nesting_steps): # Use max_nesting_steps as a safeguard against infinite loops
            FreeCAD.Console.PrintMessage(f"  [Cycle {i+1}] Starting cycle for part {part.id}.\n")

            # --- Phase 1: Gravity Movement ---
            # Record position before applying gravity.
            pre_gravity_x, pre_gravity_y, _, _ = part.bounding_box()
            FreeCAD.Console.PrintMessage(f"    Phase 1 (Gravity): Start pos ({pre_gravity_x:.2f}, {pre_gravity_y:.2f}). Applying gravity...\n")
            self._apply_gravity_to_part(part, sheet, direction)
            post_gravity_x, post_gravity_y, _, _ = part.bounding_box()
            FreeCAD.Console.PrintMessage(f"    Phase 1 (Gravity): End pos ({post_gravity_x:.2f}, {post_gravity_y:.2f}).\n")

            # --- Phase 2: Shake on Collision ---
            # The part is now at its resting place. Try to shake it to find a better fit.
            pre_shake_x, pre_shake_y, _, _ = part.bounding_box()
            FreeCAD.Console.PrintMessage(f"    Phase 2 (Anneal): Start pos ({pre_shake_x:.2f}, {pre_shake_y:.2f}). Annealing...\n")
            
            # The _anneal_part function returns the new position if successful, or the original position if not.
            # We compare the returned centroid with the part's current centroid to see if a change occurred.
            new_pos, new_rot = self._anneal_part(part, sheet, direction, rotate_enabled=self.anneal_rotate_enabled, translate_enabled=self.anneal_translate_enabled)
            
            post_shake_x, post_shake_y, _, _ = part.bounding_box()
            FreeCAD.Console.PrintMessage(f"    Phase 2 (Anneal): End pos ({post_shake_x:.2f}, {post_shake_y:.2f}).\n")

            # --- Phase 3: Check if Settled ---
            # A part is settled if it did not move during the gravity phase AND it did not
            # find a new position during the annealing phase. If it found a new position
            # during annealing, we loop again to re-apply gravity from that new spot.
            gravity_moved = abs(post_gravity_x - pre_gravity_x) > 1e-6 or abs(post_gravity_y - pre_gravity_y) > 1e-6
            shake_moved = abs(post_shake_x - post_gravity_x) > 1e-6 or abs(post_shake_y - post_gravity_y) > 1e-6
            
            FreeCAD.Console.PrintMessage(f"    Phase 3 (Settle Check): Gravity moved: {gravity_moved}, Shake moved: {shake_moved}.\n")

            if not gravity_moved and not shake_moved:
                FreeCAD.Console.PrintMessage(f"  [Cycle {i+1}] Part has settled. Exiting loop.\n")
                break

        return part