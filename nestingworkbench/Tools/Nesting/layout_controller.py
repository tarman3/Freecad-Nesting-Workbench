# Nesting/nesting/layout_controller.py

"""
This module contains the LayoutController class, which is responsible for managing
and drawing a complete nesting layout, including both final and preview states.
"""

# Standard library imports
import copy
import math

# FreeCAD imports
import FreeCAD
import Part

# Local application/library specific imports
from Nesting.nestingworkbench.datatypes.shape_object import create_shape_object
from Nesting.nestingworkbench.datatypes.sheet_object import create_sheet
from Nesting.nestingworkbench.datatypes.label_object import create_label_object

try:
    from shapely.affinity import translate
except ImportError:
    translate = None

try:
    import Draft
except ImportError:
    Draft = None

class LayoutController:
    """
    Manages the state and representation of a nested layout, including all
    sheets and the parts placed on them.
    """
    def __init__(self, obj):
        """
        This is now the constructor for the scripted object proxy.
        It's called when a new LayoutObject is created.
        """
        obj.Proxy = self
        self.obj = obj
        self.sheets = []
        self.master_shapes = []
        self.ui_params = {}
        self.unplaced_parts = []

    def setup(self, sheets, ui_params, master_shapes, unplaced_parts):
        """A method to pass run-time data to the proxy before execution."""
        self.sheets = sheets
        self.ui_params = ui_params
        self.master_shapes = master_shapes
        self.unplaced_parts = unplaced_parts

    def calculate_sheet_fills(self):
        """Calculates the fill percentage for each sheet in the layout."""
        return [sheet.calculate_fill_percentage() for sheet in self.sheets]

    def _create_layout_group(self):
        """
        Creates or finds the main layout group and populates it with properties
        and parameters from the nesting run.
        """
        parent_group = self.obj # The scripted object itself is the group
        parent_group.addProperty("App::PropertyBool", "IsStacked", "Nesting").IsStacked = False
        parent_group.addProperty("App::PropertyMap", "OriginalPlacements", "Nesting")

        # Store parameters directly on the layout group object
        parent_group.addProperty("App::PropertyFloat", "SheetWidth", "Nesting").SheetWidth = self.ui_params.get('sheet_w', 0)
        parent_group.addProperty("App::PropertyFloat", "SheetHeight", "Nesting").SheetHeight = self.ui_params.get('sheet_h', 0)
        parent_group.addProperty("App::PropertyFloat", "PartSpacing", "Nesting").PartSpacing = self.ui_params.get('spacing', 0)
        parent_group.addProperty("App::PropertyFile", "FontFile", "Nesting").FontFile = self.ui_params.get('font_path', '')

        # Store efficiencies in a PropertyMap
        sheet_fills = self.calculate_sheet_fills()
        if sheet_fills:
            parent_group.addProperty("App::PropertyMap", "SheetEfficiencies", "Nesting")
            efficiencies_map = {f"Sheet_{i+1}": f"{eff:.2f}%" for i, eff in enumerate(sheet_fills)}
            parent_group.SheetEfficiencies = efficiencies_map
        return parent_group

    def execute(self, fp):
        """Creates the final layout group and draws all sheets and their contents."""
        # fp is the feature python object (self.obj)
        parent_group = fp
        
        # --- Create and populate the hidden MasterShapes group ---
        if self.master_shapes:
            master_shapes_group = self.doc.addObject("App::DocumentObjectGroup", "MasterShapes")
            for shape_wrapper in self.master_shapes: # shape_wrapper is a Shape object
                original_obj = shape_wrapper.source_freecad_object
                # Create a ShapeObject to store as the master, leaving the original untouched.
                master_obj = create_shape_object(f"master_{original_obj.Label.replace('master_', '').replace('nested_', '')}")
                
                # The shape_bounds.source_centroid contains the necessary offset to align
                # the shape with its origin-centered boundary polygon.
                shape_copy = original_obj.Shape.copy()
                if shape_wrapper.shape_bounds and shape_wrapper.shape_bounds.source_centroid:
                    shape_copy.translate(-shape_wrapper.shape_bounds.source_centroid)
                
                master_obj.Shape = shape_copy
                master_shapes_group.addObject(master_obj)

                # Now, draw the bounds for this master shape and link them.
                # The bounds are drawn at the document origin (0,0,0) as they are just for reference.
                if shape_wrapper.shape_bounds and shape_wrapper.shape_bounds.polygon:
                    boundary_obj = shape_wrapper.draw_bounds(self.doc, FreeCAD.Vector(0,0,0), master_shapes_group)
                    if boundary_obj:
                        master_obj.BoundaryObject = boundary_obj
                        # Set initial visibility based on the UI checkbox
                        master_obj.ShowBounds = self.ui_params.get('show_bounds', False)
                        boundary_obj.ViewObject.Visibility = master_obj.ShowBounds

                # --- Create Label for Master Shape ---
                if self.ui_params.get('add_labels', False) and Draft and self.ui_params.get('font_path') and hasattr(shape_wrapper, 'label_text') and shape_wrapper.label_text:
                    label_obj = create_label_object(f"label_master_{original_obj.Label.replace('master_', '')}")
                    
                    # Create the underlying ShapeString geometry
                    shapestring_geom = Draft.make_shapestring(
                        String=shape_wrapper.label_text,
                        FontFile=self.ui_params['font_path'],
                        Size=self.ui_params.get('spacing', 0) * 0.6
                    )
                    label_obj.Shape = shapestring_geom.Shape
                    self.doc.removeObject(shapestring_geom.Name) # Remove the temporary Draft object

                    # Center the label on the master shape's bounding box
                    shapestring_bb = label_obj.Shape.BoundBox
                    shapestring_center = shapestring_bb.Center
                    
                    # Master shape is at origin, so its center is its bounding box center.
                    master_shape_center = master_obj.Shape.BoundBox.Center
                    master_shape_center.z += self.ui_params.get('label_height', 0.1)

                    label_placement_base = master_shape_center - shapestring_center
                    label_obj.Placement = FreeCAD.Placement(label_placement_base, FreeCAD.Rotation())

                    master_shapes_group.addObject(label_obj)
                    master_obj.LabelObject = label_obj # Link to property
                    master_obj.ShowLabel = self.ui_params.get('add_labels', False) # Set initial visibility
                    label_obj.ViewObject.Visibility = master_obj.ShowLabel

            parent_group.addObject(master_shapes_group)
            # Hide the group itself
            if FreeCAD.GuiUp and hasattr(master_shapes_group, "ViewObject"):
                master_shapes_group.ViewObject.Visibility = False

        spacing = self.ui_params.get('spacing', 0)

        # Iterate through the sheets and delegate drawing to the Sheet object itself
        for sheet in self.sheets:
            sheet_origin = sheet.get_origin(spacing)
            sheet.draw( # The sheet.draw method will now be called inside execute
                fp.Document,
                sheet_origin,
                self.ui_params,
                parent_group=parent_group,
                draw_shape=True, # Always draw the shape in the final layout
                draw_shape_bounds=self.ui_params.get('show_bounds', False)
            )

    @property
    def doc(self):
        return self.obj.Document
