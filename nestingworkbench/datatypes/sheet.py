# Nesting/nesting/datatypes/sheet.py

"""
This module contains the Sheet class, which represents a single bin or sheet
in the nesting layout.
"""

import FreeCAD
import Part

try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False

try:
    import Draft
except ImportError:
    Draft = None

from .shape_object import create_shape_object
from .label_object import create_label_object

class Sheet:
    """
    Represents a single sheet (or bin) in the nesting layout. It contains
    the parts that have been placed on it.
    """
    def __init__(self, sheet_id, width, height):
        self.id = sheet_id
        self.width = width
        self.height = height
        self.parts = [] # List of PlacedPart objects
        self._union_of_placed_parts = None
        self._union_is_dirty = True
        self.parent_group_name = None # Will store the name of the top-level layout group

    def __repr__(self):
        return f"<Sheet id={self.id}, parts={len(self.parts)}>"

    def __iter__(self):
        """Allows iterating directly over the parts on the sheet."""
        return iter(self.parts)

    def __len__(self):
        """Returns the number of parts on the sheet."""
        return len(self.parts)

    def add_part(self, placed_part):
        """Adds a part to the sheet and marks the union cache as dirty."""
        self.parts.append(placed_part)
        self._union_is_dirty = True

    def get_origin(self, spacing=0):
        """
        Calculates the origin (bottom-left corner) of this sheet in a layout.

        Args:
            spacing (float): The horizontal distance between sheets.

        Returns:
            FreeCAD.Vector: The calculated origin vector.
        """
        return FreeCAD.Vector(self.id * (self.width + spacing), 0, 0)

    def calculate_fill_percentage(self, use_unbuffered_area=True):
        """
        Calculates the fill percentage of the sheet.

        Args:
            use_unbuffered_area (bool): If True, uses the original part area without spacing.
                                        If False, uses the buffered area (including spacing).

        Returns:
            float: The fill percentage (0-100), or 0 if sheet area is zero.
        """
        sheet_area = self.width * self.height
        if sheet_area == 0:
            return 0.0

        total_part_area = 0
        for part in self.parts:
            if part.shape:
                if use_unbuffered_area and part.shape.unbuffered_polygon:
                    total_part_area += part.shape.unbuffered_polygon.area
                elif part.shape.polygon: # Fallback to buffered
                    total_part_area += part.shape.polygon.area
        
        return (total_part_area / sheet_area) * 100.0

    def get_union_of_placed_parts(self, force_recalculate=False, part_to_ignore=None):
        """Returns a cached union of all parts on the sheet, recalculating if necessary."""
        if self._union_is_dirty or force_recalculate:
            polygons_to_union = []
            for p in self.parts:
                # Exclude the part to ignore from the union calculation
                if p.shape != part_to_ignore and p.shape and p.shape.polygon:
                    polygons_to_union.append(p.shape.polygon)
            self._union_of_placed_parts = unary_union(polygons_to_union) if polygons_to_union else None
            self._union_is_dirty = False
        return self._union_of_placed_parts

    def is_placement_valid(self, shape_to_check, recalculate_union=False, part_to_ignore=None):
        """
        Checks if a shape's placement is valid on this sheet, considering both
        containment and collision with existing parts.

        Args:
            shape_to_check (Shape): The shape instance with its bounds polygon at the desired location.
            recalculate_union (bool): If True, forces a recalculation of the union of placed parts.
            part_to_ignore (Shape, optional): A specific shape to exclude from the union calculation.

        Returns:
            bool: True if the placement is valid, False otherwise.
        """
        if not SHAPELY_AVAILABLE: return False
        if not shape_to_check.polygon: return False

        # 1. Check containment within sheet boundaries
        bin_polygon = Polygon([(0, 0), (self.width, 0), (self.width, self.height), (0, self.height)])
        if not bin_polygon.contains(shape_to_check.polygon):
            return False

        union_of_placed_parts = self.get_union_of_placed_parts(force_recalculate=False, part_to_ignore=part_to_ignore)

        # 2. Check for collision with other parts
        if union_of_placed_parts is None or union_of_placed_parts.is_empty:
            return True # No parts to collide with

        return not shape_to_check.polygon.intersects(union_of_placed_parts)

    def is_placement_valid_polygon(self, polygon_to_check, recalculate_union=False, part_to_ignore=None):
        """
        Checks if a shapely polygon's placement is valid on this sheet.
        This version is for checking raw polygons without a full Shape object.

        Args:
            polygon_to_check (shapely.geometry.Polygon): The polygon at the desired location.
            recalculate_union (bool): If True, forces a recalculation of the union of placed parts.
            part_to_ignore (Shape, optional): A specific shape to exclude from the union calculation.

        Returns:
            bool: True if the placement is valid, False otherwise.
        """
        if not SHAPELY_AVAILABLE or not polygon_to_check: return False

        bin_polygon = Polygon([(0, 0), (self.width, 0), (self.width, self.height), (0, self.height)])
        if not bin_polygon.contains(polygon_to_check):
            return False

        union_of_placed_parts = self.get_union_of_placed_parts(force_recalculate=recalculate_union, part_to_ignore=part_to_ignore)
        if union_of_placed_parts is None or union_of_placed_parts.is_empty:
            return True
        return not polygon_to_check.intersects(union_of_placed_parts)

    def draw(self, doc, sheet_origin, ui_params, parent_group, draw_shape=True, draw_shape_bounds=False):
        """
        Draws the sheet and its contents into the FreeCAD document.

        Args:
            doc (FreeCAD.Document): The active document.
            sheet_origin (FreeCAD.Vector): The origin vector for this sheet.
            ui_params (dict): A dictionary of parameters from the UI.
            parent_group (App.DocumentObjectGroup): The main layout group to add this sheet to.
            draw_shape (bool): If True, draws the final FreeCAD part.
            draw_shape_bounds (bool): If True, draws the shapely boundary polygon.
        """
        # Store the parent group name for later reference (e.g., by the bounds toggle)
        self.parent_group_name = parent_group.Name

        # Create the group structure for this sheet
        sheet_group = doc.addObject("App::DocumentObjectGroup", f"Sheet_{self.id+1}") # e.g. Sheet_1
        shapes_group = doc.addObject("App::DocumentObjectGroup", f"Shapes_{self.id+1}") # e.g. Shapes_1
        text_group = doc.addObject("App::DocumentObjectGroup", f"Text_{self.id+1}")
        sheet_group.addObject(shapes_group)
        sheet_group.addObject(text_group)
        parent_group.addObject(sheet_group)

        # Draw sheet boundary
        sheet_obj = doc.addObject("Part::Feature", f"Sheet_Boundary_{self.id+1}")
        sheet_obj.Shape = Part.makePlane(self.width, self.height)
        sheet_obj.Placement = FreeCAD.Placement(sheet_origin, FreeCAD.Rotation())
        sheet_group.addObject(sheet_obj)
        if FreeCAD.GuiUp:
            sheet_obj.ViewObject.Transparency = 75

        # Draw the parts placed on this sheet
        FreeCAD.Console.PrintMessage(f"DEBUG: --- Drawing Sheet {self.id+1} --- \n")
        for placed_part in self.parts:
            shape = placed_part.shape
            FreeCAD.Console.PrintMessage(f"DEBUG:   Attempting to draw part '{shape.id}' (id={id(shape)}). Checking for fc_object...\n")
            # The final placement is now pre-calculated by the nester and stored on the shape object.
            # We should use this directly instead of recalculating it.
            final_placement = shape.placement

            shape_obj = shape.fc_object
            if shape_obj:
                FreeCAD.Console.PrintMessage(f"DEBUG:     fc_object '{shape_obj.Label}' found. Proceeding with drawing.\n")

                # Create a container to hold the part and its bounds, which will be rotated.
                container = doc.addObject("App::Part", f"nested_{shape.id}")
                shapes_group.addObject(container)

                # Place the boundary object at the container's origin. It is the reference.
                boundary_obj = shape_obj.BoundaryObject
                if boundary_obj:
                    boundary_obj.Placement = FreeCAD.Placement()
                    container.addObject(boundary_obj)

                # Place the shape object inside the container, offsetting it by -source_centroid
                # to align it with the boundary object.
                if shape.source_centroid:
                    shape_obj.Placement = FreeCAD.Placement(shape.source_centroid.negative(), FreeCAD.Rotation())
                else:
                    shape_obj.Placement = FreeCAD.Placement()
                container.addObject(shape_obj)

                # Apply the final nesting placement to the CONTAINER.
                # All objects within it (shape, bounds) will be transformed together.
                container.Placement = final_placement
                FreeCAD.Console.PrintMessage(f"DEBUG: PLACEMENT for '{container.Label}': {container.Placement}")

                # --- Handle the label object AFTER the container is placed ---
                # This ensures the label is not affected by the container's rotation
                # and its world position can be calculated accurately.
                if ui_params.get('add_labels', False) and Draft and ui_params.get('font_path') and hasattr(shape, 'label_text') and shape.label_text:
                    label_obj = create_label_object(f"label_{shape.id}")
                    shapestring_geom = Draft.make_shapestring(String=shape.label_text, FontFile=ui_params['font_path'], Size=ui_params.get('spacing', 0) * 0.6)
                    label_obj.Shape = shapestring_geom.Shape
                    doc.removeObject(shapestring_geom.Name)
                    
                    shapestring_center = label_obj.Shape.BoundBox.Center
                    
                    # The pivot point of the aligned shape in world coordinates is the base of the container's final placement.
                    final_part_center = container.Placement.Base
                    
                    # We will center the label on this point, adding the Z offset from the UI.
                    target_label_center = final_part_center + FreeCAD.Vector(0, 0, ui_params.get('label_height', 0.1))
                    
                    # The label should not rotate, so its placement is a simple translation.
                    label_placement_base = target_label_center - shapestring_center
                    label_obj.Placement = FreeCAD.Placement(label_placement_base, FreeCAD.Rotation()) # No rotation
                    
                    # Add the label to the dedicated, non-rotated text_group
                    text_group.addObject(label_obj)
                    shape_obj.LabelObject = label_obj

                # Set visibility on the main shape object
                shape_obj.ShowShape = True
                shape_obj.ShowBounds = ui_params.get('show_bounds', False)
                shape_obj.ShowLabel = ui_params.get('add_labels', False)
            else:
                FreeCAD.Console.PrintWarning(f"DEBUG:     fc_object for part '{shape.id}' was None. Skipping drawing.\n")