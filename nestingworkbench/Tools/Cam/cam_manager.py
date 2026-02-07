# Nesting/nesting/cam_manager.py

"""
This module contains the CAMManager class, which is responsible for creating
and managing CAM jobs from the nested layouts.
"""

import FreeCAD

class CAMManager:
    """Manages the creation of FreeCAD CAM jobs from nested layouts."""
    def __init__(self, layout_group):
        self.doc = FreeCAD.ActiveDocument
        self.layout_group = layout_group

    def create_cam_job(self, include_parts=True, include_labels=True, include_outlines=False):
        """Main method to create the CAM job.
        
        Args:
            include_parts: Include part_* objects (full cuts)
            include_labels: Include label_* objects (engraving)
            include_outlines: Include outline_* objects (silhouettes)
        """
        if not self.layout_group:
             FreeCAD.Console.PrintError("No layout group provided.\\n")
             return

        # Iterate over the layout group to find sheet groups directly
        for obj in self.layout_group.Group:
            # We assume groups starting with "Sheet_" are the sheet containers
            if obj.isDerivedFrom("App::DocumentObjectGroup") and obj.Label.startswith("Sheet_"):
                self._create_job_for_sheet(obj, include_parts, include_labels, include_outlines)


    def _create_job_for_sheet(self, sheet_group, include_parts=True, include_labels=True, include_outlines=False):
        """Creates a CAM job for a sheet with proper stock dimensions.
        
        Args:
            sheet_group: The Sheet_X group to process
            include_parts: Include part_* objects (full cuts)
            include_labels: Include label_* objects (engraving)
            include_outlines: Include outline_* objects (silhouettes)
        """
        # Import CAM modules (FreeCAD 1.1+)
        try:
            from CAM.Path.Main import Job as PathJob
            from CAM.Path.Main import Stock as PathStock
        except ImportError as e:
            FreeCAD.Console.PrintError(f"Failed to import CAM modules. Error: {e}\\n")
            FreeCAD.Console.PrintError("Please ensure the CAM workbench is installed and enabled in FreeCAD 1.1+.\\n")
            return
        
        # Get layout parameters from layout properties (preferred) or spreadsheet (fallback)
        sheet_width = 600.0  # Default values
        sheet_height = 600.0
        sheet_thickness = 3.0
        
        # Try to read from layout group properties first (most reliable)
        if self.layout_group:
            if hasattr(self.layout_group, 'SheetWidth'):
                sheet_width = float(self.layout_group.SheetWidth)
            if hasattr(self.layout_group, 'SheetHeight'):
                sheet_height = float(self.layout_group.SheetHeight)
            if hasattr(self.layout_group, 'SheetThickness'):
                sheet_thickness = float(self.layout_group.SheetThickness)
            
            # Fallback to spreadsheet if properties don't exist
            if not hasattr(self.layout_group, 'SheetWidth'):
                spreadsheet = self.layout_group.getObject("LayoutParameters")
                if spreadsheet:
                    try:
                        # Read sheet dimensions
                        width_val = spreadsheet.get('B2')
                        if width_val:
                            sheet_width = float(width_val)
                        height_val = spreadsheet.get('B3')
                        if height_val:
                            sheet_height = float(height_val)
                        # Read sheet thickness  
                        thickness_val = spreadsheet.get('B5')
                        if thickness_val:
                            sheet_thickness = float(thickness_val)
                    except Exception as e:
                        FreeCAD.Console.PrintWarning(f"Could not read parameters from spreadsheet: {e}\\n")
        
        # Collect transformed shapes for CAM
        # We need to bake container placements into the geometry since CAM
        # doesn't correctly handle objects nested in App::Part containers
        parts_shapes = []
        labels_shapes = []
        outlines_shapes = []
        
        for obj in sheet_group.Group:
            # Check for the Parts container (Shapes_X)
            if obj.Label.startswith("Shapes_") and obj.isDerivedFrom("App::DocumentObjectGroup"):
                for nested_part in obj.Group:
                    if nested_part.isDerivedFrom("App::Part") and nested_part.Label.startswith("nested_"):
                        # Get container placement
                        container_placement = nested_part.Placement
                        
                        # Find the part_*, label_*, and outline_* shapes inside the container
                        for child in nested_part.Group:
                            if hasattr(child, 'Shape') and child.Shape and not child.Shape.isNull():
                                # Transform shape to global coordinates
                                combined_placement = container_placement.multiply(child.Placement)
                                transformed_shape = child.Shape.copy()
                                transformed_shape.Placement = FreeCAD.Placement()
                                transformed_shape = transformed_shape.transformGeometry(combined_placement.toMatrix())
                                
                                if include_parts and child.Label.startswith("part_"):
                                    # Adjust Z so bottom is at Z = -sheet_thickness
                                    z_min = transformed_shape.BoundBox.ZMin
                                    z_offset = -sheet_thickness - z_min
                                    z_placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, z_offset), FreeCAD.Rotation())
                                    transformed_shape = transformed_shape.transformGeometry(z_placement.toMatrix())
                                    parts_shapes.append(transformed_shape)
                                
                                elif include_labels and child.Label.startswith("label_"):
                                    # Labels at Z = 0
                                    z_min = transformed_shape.BoundBox.ZMin
                                    z_offset = -z_min
                                    z_placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, z_offset), FreeCAD.Rotation())
                                    transformed_shape = transformed_shape.transformGeometry(z_placement.toMatrix())
                                    labels_shapes.append(transformed_shape)
                                
                                elif include_outlines and child.Label.startswith("outline_"):
                                    outlines_shapes.append(transformed_shape)
        
        if not (parts_shapes or labels_shapes or outlines_shapes):
            FreeCAD.Console.PrintWarning(f"No objects selected for CAM in {sheet_group.Label}. Skipping.\\n")
            return
        
        # Build status message
        counts = []
        if parts_shapes:
            counts.append(f"{len(parts_shapes)} parts")
        if labels_shapes:
            counts.append(f"{len(labels_shapes)} labels")
        if outlines_shapes:
            counts.append(f"{len(outlines_shapes)} outlines")
        FreeCAD.Console.PrintMessage(f"Creating CAM job with {', '.join(counts)}...\\n")
        
        # Create compound objects for CAM (one per type)
        # This minimizes the number of base objects
        import Part
        all_models = []
        
        if parts_shapes:
            parts_compound = self.doc.addObject("Part::Feature", f"CAM_Parts_{sheet_group.Label}")
            parts_compound.Shape = Part.Compound(parts_shapes)
            if hasattr(parts_compound, 'ViewObject') and parts_compound.ViewObject:
                parts_compound.ViewObject.Visibility = False
            all_models.append(parts_compound)
        
        if labels_shapes:
            labels_compound = self.doc.addObject("Part::Feature", f"CAM_Labels_{sheet_group.Label}")
            labels_compound.Shape = Part.Compound(labels_shapes)
            if hasattr(labels_compound, 'ViewObject') and labels_compound.ViewObject:
                labels_compound.ViewObject.Visibility = False
            all_models.append(labels_compound)
        
        if outlines_shapes:
            outlines_compound = self.doc.addObject("Part::Feature", f"CAM_Outlines_{sheet_group.Label}")
            outlines_compound.Shape = Part.Compound(outlines_shapes)
            if hasattr(outlines_compound, 'ViewObject') and outlines_compound.ViewObject:
                outlines_compound.ViewObject.Visibility = False
            all_models.append(outlines_compound)
        
        # Use GUI Create function which properly sets up all Model-Job linking
        try:
            import FreeCADGui
            from CAM.Path.Main.Gui import Job as PathJobGui
            
            # Use the GUI create function with openTaskPanel=False so it doesn't pop up a dialog
            job = PathJobGui.Create(all_models, None, openTaskPanel=False)
            
            if job:
                # Rename the job to our desired name
                job.Label = f"CAM_Job_{sheet_group.Label}"
                
                # Note: CAM_Parts/Labels/Outlines compounds are hidden base objects
                # that the CAM job references. They cannot be deleted.
                
                # Replace the stock with a CreateBox stock matching sheet dimensions
                if job.Stock:
                    old_stock = job.Stock
                    self.doc.removeObject(old_stock.Name)
                
                # Create new box stock with sheet dimensions
                # Position stock at sheet origin, Z positioned to match where parts are
                new_stock = PathStock.CreateBox(job)
                new_stock.Length = sheet_width
                new_stock.Width = sheet_height
                new_stock.Height = sheet_thickness
                
                # Stock positioned with bottom at Z = -sheet_thickness, top at Z = 0
                # This matches the parts which have their bottom at Z = -sheet_thickness
                new_stock.Placement = FreeCAD.Placement(
                    FreeCAD.Vector(0, 0, -sheet_thickness),
                    FreeCAD.Rotation()
                )
                job.Stock = new_stock
                
                # Set post processor to GRBL
                try:
                    job.PostProcessor = "grbl"
                    job.PostProcessorOutputFile = ""  # Will use default naming
                except Exception as e:
                    FreeCAD.Console.PrintWarning(f"Could not set post processor: {e}\\n")
                
                # Ensure models are visible
                if hasattr(job, 'Model') and job.Model:
                    if hasattr(job.Model, 'ViewObject') and job.Model.ViewObject:
                        job.Model.ViewObject.Visibility = True
                    if hasattr(job.Model, 'Group'):
                        for model_obj in job.Model.Group:
                            if hasattr(model_obj, 'ViewObject') and model_obj.ViewObject:
                                model_obj.ViewObject.Visibility = True
                
                # Recompute to finalize the job
                self.doc.recompute()
                
                FreeCAD.Console.PrintMessage(f"Created CAM job '{job.Label}' for {sheet_group.Label} (stock: {sheet_width}x{sheet_height}x{sheet_thickness}mm)\\n")
            else:
                FreeCAD.Console.PrintError("Failed to create CAM job.\\n")
                
        except Exception as e:
            FreeCAD.Console.PrintError(f"Error creating CAM job: {e}\\n")
            import traceback
            traceback.print_exc()

