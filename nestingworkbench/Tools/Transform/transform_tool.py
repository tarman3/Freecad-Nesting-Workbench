# Nesting/nestingworkbench/Tools/Transform/transform_tool.py

"""
This module contains the TransformToolObserver class, which implements a
simple drag-and-drop functionality for manually transforming parts in a layout.
"""

import FreeCAD
import FreeCADGui
from PySide import QtCore
import time
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
        self.callback_ids = []  # Store callback IDs for cleanup
        self.last_log_time = 0

        # Get the selected layout group
        selection = FreeCADGui.Selection.getSelection()
        if selection and selection[0].isDerivedFrom("App::DocumentObjectGroup") and selection[0].Label.startswith("Layout_"):
            self.layout_group = selection[0]
        else:
            FreeCAD.Console.PrintWarning("Transform Tool: Please select a Layout group first.\n")
            return

        # Store original placements and manage visibility
        print(f"DEBUG: Traversing Layout Group: {self.layout_group.Label}")
        for sheet_group in self.layout_group.Group:
            print(f"DEBUG: Checking sheet_group: {sheet_group.Label} (Type: {sheet_group.TypeId})")
            if sheet_group.isDerivedFrom("App::DocumentObjectGroup"):
                # Ensure sheet boundary is visible
                sheet_boundary = next((obj for obj in sheet_group.Group if obj.Label.startswith("Sheet_Boundary_")), None)
                if sheet_boundary and hasattr(sheet_boundary, "ViewObject"):
                    self.original_visibilities[sheet_boundary] = sheet_boundary.ViewObject.Visibility
                    sheet_boundary.ViewObject.Visibility = True
                
                print(f"DEBUG: Sheet Group content count: {len(sheet_group.Group)}")
                for sub_group in sheet_group.Group: # e.g., Shapes_1, Text_1
                    print(f"DEBUG: Checking sub_group: {sub_group.Label} (Type: {sub_group.TypeId})")
                    if sub_group.isDerivedFrom("App::DocumentObjectGroup"):
                        if sub_group.Label.startswith("Shapes_"):
                            print(f"DEBUG: Found Shapes group: {sub_group.Label}")
                            for obj in sub_group.Group: # e.g., nested_PartA_1
                                # print(f"DEBUG: Inspecting obj: {obj.Label} Proxy: {obj.Proxy.__class__.__name__ if hasattr(obj, 'Proxy') else 'None'}")
                                
                                has_shape_proxy = hasattr(obj, "Proxy") and isinstance(obj.Proxy, object) and obj.Proxy.__class__.__name__ == "ShapeObject"
                                # Relaxed check: allow if it has the proxy OR if it's in the Shapes group (likely a nested part without proxy)
                                if has_shape_proxy or True: 
                                    # print(f"DEBUG: Tracking ShapeObject: {obj.Label}")
                                    self.original_placements[obj] = obj.Placement.copy()
                                    if hasattr(obj, "ViewObject"):
                                        self.original_visibilities[obj] = obj.ViewObject.Visibility
                                        
                                        # Manage visibility of linked objects (BoundaryObject and LabelObject)
                                        replacement_shown = False
                                        if hasattr(obj, "BoundaryObject") and obj.BoundaryObject and hasattr(obj.BoundaryObject, "ViewObject"):
                                            self.original_visibilities[obj.BoundaryObject] = obj.BoundaryObject.ViewObject.Visibility
                                            obj.BoundaryObject.ViewObject.Visibility = True # Always show bounds in transform mode
                                            replacement_shown = True
                                        if hasattr(obj, "LabelObject") and obj.LabelObject and hasattr(obj.LabelObject, "ViewObject"):
                                            self.original_visibilities[obj.LabelObject] = obj.LabelObject.ViewObject.Visibility
                                            obj.LabelObject.ViewObject.Visibility = True # Always show label in transform mode
                                            replacement_shown = True
                                        
                                        # Only hide the original 3D shape if we are showing a replacement (Boundary/Label)
                                        if replacement_shown:
                                            obj.ViewObject.Visibility = False 

                        elif sub_group.Label.startswith("Text_"):
                             # print(f"DEBUG: Found Text group: {sub_group.Label}")
                             for label_obj in sub_group.Group: # e.g., label_unplaced_PartB
                                if hasattr(label_obj, "Proxy") and isinstance(label_obj.Proxy, object) and label_obj.Proxy.__class__.__name__ == "LabelObject":
                                    # print(f"DEBUG: Tracking LabelObject: {label_obj.Label}")
                                    self.original_placements[label_obj] = label_obj.Placement.copy()
                                    if hasattr(label_obj, "ViewObject"):
                                        self.original_visibilities[label_obj] = label_obj.ViewObject.Visibility
                                        label_obj.ViewObject.Visibility = True # Ensure standalone labels are visible

        # After changing visibilities, we need to update the GUI to reflect them.
        FreeCADGui.updateGui()
        
        # Debug: list tracked objects
        print("DEBUG: Tracked objects in original_placements:")
        for obj in self.original_placements:
           print(f"  - {obj.Label if hasattr(obj, 'Label') else obj} (Name: {obj.Name if hasattr(obj, 'Name') else 'No Name'})")

        # Register event callbacks for mouse interaction
        if self.layout_group:
            cb_id = self.view.addEventCallback("SoMouseButtonEvent", self._make_callback("SoMouseButtonEvent"))
            self.callback_ids.append(("SoMouseButtonEvent", cb_id))
            cb_id = self.view.addEventCallback("SoLocation2Event", self._make_callback("SoLocation2Event"))
            self.callback_ids.append(("SoLocation2Event", cb_id))
            FreeCAD.Console.PrintMessage("Transform Tool: Activated. Click and drag parts to move them.\n")


    def eventCallback(self, event_type, event):
        """The main callback method for handling mouse events."""
        try:
            if not self.layout_group:
                return False # Do not handle events if no layout is selected

            if event_type == "SoMouseButtonEvent":
                if event["State"] == "DOWN" and event["Button"] == "BUTTON1":
                    pos = event["Position"]
                    # pos is a tuple (x, y)
                    print(f"DEBUG: Clicked at {pos}")
                    info = self.view.getObjectInfo((pos[0], pos[1]))
                    # print(f"DEBUG: Info keys: {info.keys() if info else 'None'}")
                    if info and "Object" in info:
                        if "ParentObject" in info:
                            print(f"DEBUG: ParentObject: {info['ParentObject']}")

                        raw_obj = info["Object"]
                        clicked_obj = raw_obj
                        
                        # Handle case where Object is just the name string
                        if isinstance(raw_obj, str):
                            # print(f"DEBUG: 'Object' info is string: {raw_obj}. resolving...")
                            if self.layout_group and hasattr(self.layout_group, 'Document'):
                                clicked_obj = self.layout_group.Document.getObject(raw_obj)
                            else:
                                clicked_obj = FreeCAD.ActiveDocument.getObject(raw_obj)
                        
                        print(f"DEBUG: Clicked Object Label: {clicked_obj.Label if hasattr(clicked_obj, 'Label') else 'No Label'}")
                        print(f"DEBUG: Clicked Object Name: {clicked_obj.Name if hasattr(clicked_obj, 'Name') else 'No Name'}")
                        
                        parent_obj_from_click = info.get("ParentObject") if info else None
                        
                        obj_to_drag = self.get_draggable_parent(clicked_obj, parent_obj_from_click)
                        print(f"DEBUG: Draggable Parent: {obj_to_drag.Label if obj_to_drag and hasattr(obj_to_drag, 'Label') else 'None'}")
                        
                        if obj_to_drag:
                            self.pressed = True
                            self.obj_to_move = obj_to_drag
                            self.start_pos = self.view.getPoint(pos[0], pos[1])
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
                    
                    # Throttled logging
                    current_time = time.time()
                    if current_time - self.last_log_time > 0.25:
                        print(f"DEBUG: Dragging at {pos}")
                        self.last_log_time = current_time

                    current_pos = self.view.getPoint(pos[0], pos[1])
                    
                    # Project movement onto the XY plane
                    move_vec = current_pos - self.start_pos
                    move_vec.z = 0

                    new_placement = self.start_placement.copy()
                    new_placement.Base += move_vec
                    self.obj_to_move.Placement = new_placement
                    return True # Event handled
            
            return False # Event not handled

        except Exception:
            import traceback
            traceback.print_exc()
            return False

    def _make_callback(self, event_type):
        """Creates a callback wrapper that passes the event type to eventCallback."""
        def callback(event_dict):
            return self.eventCallback(event_type, event_dict)
        return callback

    def get_draggable_parent(self, obj, parent_obj_from_click=None):
        """
        Determines the actual object to drag based on what was clicked.
        Supports:
        1. Direct match with tracked object.
        2. Linked object matching (App::Link).
        3. Parent containment matching (App::Part containing clicked object).
        4. Matching via 'ParentObject' from click info.
        """        
        # Check if the clicked object is a linked boundary or label of a ShapeObject
        for potential_parent_shape_obj in self.original_placements.keys():
            if hasattr(potential_parent_shape_obj, "Proxy") and isinstance(potential_parent_shape_obj.Proxy, object) and potential_parent_shape_obj.Proxy.__class__.__name__ == "ShapeObject":
                if hasattr(potential_parent_shape_obj, "BoundaryObject") and potential_parent_shape_obj.BoundaryObject == obj:
                    return potential_parent_shape_obj # Drag the ShapeObject parent
                if hasattr(potential_parent_shape_obj, "LabelObject") and potential_parent_shape_obj.LabelObject == obj:
                    return potential_parent_shape_obj # Drag the ShapeObject parent
        
        # Check if the clicked object itself is tracked
        if obj in self.original_placements:
            return obj

        # Check against tracked objects with advanced logic
        for tracked_obj in self.original_placements.keys():
            if tracked_obj == obj:
                 return tracked_obj
            
            # LINK MATCHing
            if hasattr(tracked_obj, "LinkedObject") and tracked_obj.LinkedObject == obj:
                print(f"DEBUG: Matched via LinkedObject: {tracked_obj.Label} -> {obj.Label}")
                return tracked_obj

            # PARENT CONTAINMENT MATCHING (For App::Part)
            # Check if clicked object is inside tracked_obj's Group (recursive check might be too expensive, usually direct child)
            if hasattr(tracked_obj, "Group") and obj in tracked_obj.Group:
                 print(f"DEBUG: Matched via Group Containment: {tracked_obj.Label} contains {obj.Label}")
                 return tracked_obj
            
            # PARENT OBJECT FROM CLICK INFO MATCHING
            if parent_obj_from_click and tracked_obj == parent_obj_from_click:
                 print(f"DEBUG: Matched via ParentObject info: {tracked_obj.Label}")
                 return tracked_obj

            # NAME MATCHING (Fallback)
            if hasattr(tracked_obj, 'Name') and hasattr(obj, 'Name') and tracked_obj.Name == obj.Name:
                print(f"DEBUG: Matched by Name: {tracked_obj.Name}")
                return tracked_obj
        
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
        for event_type, callback_id in self.callback_ids:
            try:
                self.view.removeEventCallback(event_type, callback_id)
            except Exception as e:
                FreeCAD.Console.PrintWarning(f"Could not remove {event_type} callback: {e}\n")
        self.callback_ids = []
        
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