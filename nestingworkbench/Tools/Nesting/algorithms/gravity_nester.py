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
        import copy
        for _ in range(self.max_nesting_steps):
            # "Look-ahead" check: create a temporary copy to test the next move.
            # This avoids the "jitter" of moving and then reverting on collision.
            part_copy = copy.copy(part) # Shallow copy is enough, we only need position
            part_copy.move(direction[0] * self.step_size, direction[1] * self.step_size)

            if sheet.is_placement_valid(part_copy, recalculate_union=False, part_to_ignore=part):
                # The move is valid, so apply it to the real part.
                part.move(direction[0] * self.step_size, direction[1] * self.step_size)
            else:
                # Collision detected on the look-ahead. Stop moving.
                break

            if self.update_callback:
                self.update_callback(part, sheet) # Force UI update for simulation

    def _move_until_collision(self, part, sheet, direction):
        """
        Moves a part in the gravity direction step-by-step until it hits
        the bin edge or another placed part.
        If a collision occurs, it attempts to "shake" the part free once.
        """
        FreeCAD.Console.PrintMessage(f"\n--- Settling part {part.id} ---\n")
        cycle = 0
        # Loop until the part is fully settled (cannot move via gravity or annealing).
        while cycle < self.max_nesting_steps: # Use max_nesting_steps as a safeguard
            cycle += 1
            FreeCAD.Console.PrintMessage(f"  [Cycle {cycle}] Starting for part {part.id}.\n")

            # --- 1. Apply Gravity ---
            pre_gravity_x, pre_gravity_y, _, _ = part.bounding_box()
            FreeCAD.Console.PrintMessage(f"    Phase 1 (Gravity): Start pos ({pre_gravity_x:.2f}, {pre_gravity_y:.2f}).\n")
            self._apply_gravity_to_part(part, sheet, direction)
            post_gravity_x, post_gravity_y, _, _ = part.bounding_box()
            gravity_moved = abs(post_gravity_x - pre_gravity_x) > 1e-6 or abs(post_gravity_y - pre_gravity_y) > 1e-6

            if gravity_moved:
                FreeCAD.Console.PrintMessage(f"    -> Gravity moved part to ({post_gravity_x:.2f}, {post_gravity_y:.2f}). Continuing.\n")
                continue # Part is still falling, loop again.

            # --- 2. Anneal (if gravity failed) ---
            FreeCAD.Console.PrintMessage(f"    Phase 2 (Anneal): Gravity stopped. Attempting to anneal.\n")
            pre_shake_x, pre_shake_y, _, _ = part.bounding_box()
            self._anneal_part(part, sheet, direction, rotate_enabled=self.anneal_rotate_enabled, translate_enabled=self.anneal_translate_enabled)
            post_shake_x, post_shake_y, _, _ = part.bounding_box()
            shake_moved = abs(post_shake_x - pre_shake_x) > 1e-6 or abs(post_shake_y - pre_shake_y) > 1e-6

            if shake_moved:
                # The part was shaken into a new position. We must immediately check
                # if it can now fall further under gravity from this new spot.
                FreeCAD.Console.PrintMessage(f"    -> Shake was successful. Re-applying gravity from new pos ({post_shake_x:.2f}, {post_shake_y:.2f}).\n")
                self._apply_gravity_to_part(part, sheet, direction)
                post_second_gravity_x, post_second_gravity_y, _, _ = part.bounding_box()
                second_gravity_moved = abs(post_second_gravity_x - post_shake_x) > 1e-6 or abs(post_second_gravity_y - post_shake_y) > 1e-6
                
                if second_gravity_moved:
                    FreeCAD.Console.PrintMessage(f"    -> Part fell further after shake. Continuing settlement.\n")
                    continue # The part is falling again, so continue the main loop.

            # If we reach here, it means either:
            # 1. The shake failed to move the part.
            # 2. The shake succeeded, but the part could not fall any further from its new position.
            # In either case, the part is now considered fully settled.
            if not shake_moved:
                FreeCAD.Console.PrintMessage(f"    -> Anneal failed to move part. Part is settled.\n")
            else:
                FreeCAD.Console.PrintMessage(f"    -> Shake moved part, but it could not fall further. Part is settled.\n")
            break # Exit the loop.

        return part