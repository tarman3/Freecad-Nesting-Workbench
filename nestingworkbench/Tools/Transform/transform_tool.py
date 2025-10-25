# Nesting/nestingworkbench/Tools/Transform/transform_tool.py

"""
This module contains the TransformToolObserver class, which implements a
simple drag-and-drop functionality for manually transforming parts in a layout.
"""

import FreeCAD
import FreeCADGui
from PySide import QtCore
from .ui_transform import TransformToolUI

class TransformToolObserver:
    """
    A ViewObserver that captures mouse events to allow transforming (dragging)
    of parts within a selected layout group.
    """
    def __init__(self, view, panel_manager):
        self.panel_manager = panel_manager
        self.view = view
        self.pressed = False
        self.obj_to_move = None
        self.start_pos = None
        self.start_placement = None
        self.layout_group = None
        self.original_placements = {}
        self.original_visibilities = {}

        # Get the selected layout group
        selection = FreeCADGui.Selection.getSelection()
        if selection and selection[0].isDerivedFrom("App::DocumentObjectGroup") and selection[0].Label.startswith("Layout_"):
            self.layout_group = selection[0]
        else:
            FreeCAD.Console.PrintWarning("Transform Tool: Please select a Layout group first.\n")
            return

        # Store original placements and manage visibility
        for sheet_group in self.layout_group.Group:
            if sheet_group.isDerivedFrom("App::DocumentObjectGroup"):
                # Ensure sheet boundary is visible
                sheet_boundary = next((obj for obj in sheet_group.Group if obj.Label.startswith("Sheet_Boundary_")), None)
                if sheet_boundary and hasattr(sheet_boundary, "ViewObject"):
                    self.original_visibilities[sheet_boundary] = sheet_boundary.ViewObject.Visibility
                    sheet_boundary.ViewObject.Visibility = True

                for sub_group in sheet_group.Group: # e.g., Shapes_1, Text_1
                    if sub_group.isDerivedFrom("App::DocumentObjectGroup"):
                        if sub_group.Label.startswith("Shapes_"):
                            for obj in sub_group.Group: # e.g., nested_PartA_1
                                if hasattr(obj, "Proxy") and isinstance(obj.Proxy, object) and obj.Proxy.__class__.__name__ == "ShapeObject":
                                    self.original_placements[obj] = obj.Placement.copy()
                                    if hasattr(obj, "ViewObject"):
                                        self.original_visibilities[obj] = obj.ViewObject.Visibility
                                        obj.ViewObject.Visibility = False # Hide the 3D shape
                                        
                                        # Manage visibility of linked objects (BoundaryObject and LabelObject)
                                        if hasattr(obj, "BoundaryObject") and obj.BoundaryObject and hasattr(obj.BoundaryObject, "ViewObject"):
                                            self.original_visibilities[obj.BoundaryObject] = obj.BoundaryObject.ViewObject.Visibility
                                            obj.BoundaryObject.ViewObject.Visibility = True # Always show bounds in transform mode
                                        if hasattr(obj, "LabelObject") and obj.LabelObject and hasattr(obj.LabelObject, "ViewObject"):
                                            self.original_visibilities[obj.LabelObject] = obj.LabelObject.ViewObject.Visibility
                                            obj.LabelObject.ViewObject.Visibility = True # Always show label in transform mode
                        elif sub_group.Label.startswith("Text_"):
                            for label_obj in sub_group.Group: # e.g., label_unplaced_PartB
                                if hasattr(label_obj, "Proxy") and isinstance(label_obj.Proxy, object) and label_obj.Proxy.__class__.__name__ == "LabelObject":
                                    self.original_placements[label_obj] = label_obj.Placement.copy()
                                    if hasattr(label_obj, "ViewObject"):
                                        self.original_visibilities[label_obj] = label_obj.ViewObject.Visibility
                                        label_obj.ViewObject.Visibility = True # Ensure standalone labels are visible

        # After changing visibilities, we need to update the GUI to reflect them.
        FreeCADGui.updateGui()


    def eventCallback(self, event_type, event):
        """The main callback method for handling mouse events."""
        if not self.layout_group:
            return False # Do not handle events if no layout is selected

        if event_type == "SoMouseButtonEvent":
            if event["State"] == "DOWN" and event["Button"] == "BUTTON1":
                pos = event["Position"]
                info = self.view.getObjectInfo((pos.x(), pos.y()))
                if info and "Object" in info:
                    clicked_obj = info["Object"]
                    obj_to_drag = self.get_draggable_parent(clicked_obj)
                    
                    if obj_to_drag:
                        self.pressed = True
                        self.obj_to_move = obj_to_drag
                        self.start_pos = self.view.getPoint(pos.x(), pos.y())
                        self.start_placement = self.obj_to_move.Placement.copy()
                        return True # Event handled

            elif event["State"] == "UP" and event["Button"] == "BUTTON1":
                if self.pressed and self.obj_to_move:
                    self.pressed = False
                    self.obj_to_move = None
                    self.start_pos = None
                    self.start_placement = None
                    return True # Event handled

        elif event_type == "SoLocation2Event":
            if self.pressed and self.obj_to_move:
                pos = event["Position"]
                current_pos = self.view.getPoint(pos.x(), pos.y())
                
                # Project movement onto the XY plane
                move_vec = current_pos - self.start_pos
                move_vec.z = 0

                new_placement = self.start_placement.copy()
                new_placement.Base += move_vec
                self.obj_to_move.Placement = new_placement
                return True # Event handled

        return False # Event not handled

    def get_draggable_parent(self, obj):
        """
        Determines the actual object to drag based on what was clicked.
        If a child (bound_ or label_) of a ShapeObject was clicked, return the ShapeObject.
        Otherwise, return the object itself if it's a ShapeObject or a standalone label.
        """        
        # Check if the clicked object is a linked boundary or label of a ShapeObject
        for potential_parent_shape_obj in self.original_placements.keys():
            if hasattr(potential_parent_shape_obj, "Proxy") and isinstance(potential_parent_shape_obj.Proxy, object) and potential_parent_shape_obj.Proxy.__class__.__name__ == "ShapeObject":
                if hasattr(potential_parent_shape_obj, "BoundaryObject") and potential_parent_shape_obj.BoundaryObject == obj:
                    return potential_parent_shape_obj # Drag the ShapeObject parent
                if hasattr(potential_parent_shape_obj, "LabelObject") and potential_parent_shape_obj.LabelObject == obj:
                    return potential_parent_shape_obj # Drag the ShapeObject parent
        
        return None # Not a draggable object

    def is_object_in_layout(self, obj):
        """Check if an object is a child of the selected layout group."""
        # This method is now primarily used to check if a clicked object is *part* of the layout,
        # not necessarily if it's directly draggable. get_draggable_parent handles that.
        for sheet_group in self.layout_group.Group:
            if sheet_group.isDerivedFrom("App::DocumentObjectGroup"):
                for sub_group in sheet_group.Group: # e.g., Shapes_1, Text_1
                    if sub_group.isDerivedFrom("App::DocumentObjectGroup") and obj in sub_group.Group:
                        return True
        return False

    def save_placements(self): # This method is now part of the TransformToolObserver
        """Saves the new placements to the layout's OriginalPlacements property."""
        if not self.layout_group:
            return

        # The placements are already applied to the objects.
        FreeCAD.Console.PrintMessage(f"Saved new placements for transformed objects.\n")
        # If sheets were stacked, this move breaks the "stacked" state
        if hasattr(self.layout_group, 'IsStacked') and self.layout_group.IsStacked:
            self.layout_group.IsStacked = False
            FreeCAD.Console.PrintWarning("Layout is no longer considered stacked due to manual adjustment.\n")

    def cancel(self): # This method is now part of the TransformToolObserver
        """Reverts any changes made to the object placements."""
        if self.original_placements:
            for obj, placement in self.original_placements.items():
                if obj: # Check if object still exists
                    obj.Placement = placement
            FreeCAD.Console.PrintMessage("Transformations cancelled.\n")

    def cleanup(self): # This method is now part of the TransformToolObserver
        """Removes the event callbacks from the view and restores original visibilities."""
        try:
            self.view.removeEventCallback("SoMouseButtonEvent", self.eventCallback)
            self.view.removeEventCallback("SoLocation2Event", self.eventCallback)
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"Could not remove transform observer callbacks: {e}\n")
        
        self.original_placements = {}
        # Restore original visibility
        for obj, is_visible in self.original_visibilities.items():
            try:
                if hasattr(obj, "ViewObject"):
                    obj.ViewObject.Visibility = is_visible
            except Exception:
                pass # Object may have been deleted
        self.original_visibilities = {}
        
        # After restoring visibilities, update the GUI again.
        FreeCADGui.updateGui()
        self.layout_group = None