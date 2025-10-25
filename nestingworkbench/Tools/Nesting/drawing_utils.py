# Nesting/nesting/drawing_utils.py

"""
This module contains shared utility functions for drawing objects in FreeCAD.
"""

import FreeCAD
import Part
from ...datatypes.sheet_object import create_sheet

def create_face_from_polygon(polygon):
    """
    Creates a FreeCAD Part.Face from a Shapely Polygon, including holes.

    Args:
        polygon (shapely.geometry.Polygon): The polygon to convert.

    Returns:
        Part.Face: The resulting FreeCAD face, or None if conversion fails.
    """
    if not polygon or polygon.is_empty:
        return None

    # Create outer wire
    exterior_verts = [FreeCAD.Vector(v[0], v[1], 0) for v in polygon.exterior.coords]
    if len(exterior_verts) < 4: # A polygon needs at least 3 points + closing point
        return None
    outer_wire = Part.makePolygon(exterior_verts)
    try:
        face = Part.Face(outer_wire)
    except Part.OCCError:
        # If the outer wire cannot form a face, we cannot proceed.
        return None

    # Create inner wires (holes)
    for interior in polygon.interiors:
        interior_verts = [FreeCAD.Vector(v[0], v[1], 0) for v in interior.coords]
        if len(interior_verts) >= 4:
            hole_wire = Part.makePolygon(interior_verts)
            try:
                hole_face = Part.Face(hole_wire)
                face = face.cut(hole_face)
            except Part.OCCError:
                FreeCAD.Console.PrintWarning("Could not create or cut a hole for debug union shape.\n")

    return face

class LayoutDrawer:
    """A static class for handling drawing operations for nesting layouts."""

    @staticmethod
    def draw_preview(doc, preview_group, sheets, ui_params):
        """
        Draws a preview of the nesting layout, optimized for animation.
        It finds/creates and updates boundary objects for each part.
        """
        if not doc or not preview_group:
            return

        spacing = ui_params.get('spacing', 0)
        sheet_w = ui_params.get('sheet_w', 0)
        sheet_h = ui_params.get('sheet_h', 0)

        # Keep track of objects that are part of the current preview
        active_object_names = set()

        for sheet in sheets:
            # --- Draw Sheet Boundary ---
            sheet_boundary_name = f"preview_sheet_boundary_{sheet.id}"
            active_object_names.add(sheet_boundary_name)
            sheet_boundary_obj = doc.getObject(sheet_boundary_name)
            if not sheet_boundary_obj:
                sheet_boundary_obj = create_sheet(sheet_boundary_name)
                sheet_boundary_obj.SheetWidth = sheet_w
                sheet_boundary_obj.SheetHeight = sheet_h
                preview_group.addObject(sheet_boundary_obj)
            sheet_boundary_obj.Placement = FreeCAD.Placement(sheet.get_origin(spacing), FreeCAD.Rotation())

            # --- Draw Part Boundaries ---
            for part in sheet.parts:
                shape = part.shape
                bound_obj_name = f"preview_bound_{shape.id}"
                active_object_names.add(bound_obj_name)
                bound_obj = doc.getObject(bound_obj_name)

                # This logic is moved from Shape.draw_bounds
                final_polygon = shape.get_final_bounds_polygon(sheet.get_origin(spacing))
                if not final_polygon: continue

                exterior_verts = [FreeCAD.Vector(v[0], v[1], 0) for v in final_polygon.exterior.coords]
                if len(exterior_verts) < 3: continue
                
                new_shape = Part.makePolygon(exterior_verts)

                if bound_obj:
                    bound_obj.Shape = new_shape
                else:
                    bound_obj = doc.addObject("Part::Feature", bound_obj_name)
                    bound_obj.Shape = new_shape
                    preview_group.addObject(bound_obj)
                    if FreeCAD.GuiUp: bound_obj.ViewObject.LineColor = (1.0, 0.0, 0.0)

        # --- Cleanup ---
        # Remove any objects from the preview group that are not part of the current frame
        for obj in list(preview_group.Group):
            if obj.Name not in active_object_names:
                doc.removeObject(obj.Name)