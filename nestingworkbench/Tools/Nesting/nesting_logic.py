from PySide import QtGui
import FreeCAD
import Part
import copy

from .algorithms import nesting_strategy

class NestingDependencyError(Exception):
    """Custom exception for missing optional dependencies like Shapely."""
    pass

try:
    # Check for shapely availability without importing specific functions
    import shapely
    from shapely.affinity import rotate, translate
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False

# Global reference for trial visualization object
_trial_viz_obj = None

def _draw_trial_bounds(part, angle, x, y):
    """Draws the boundary polygon at a trial position during simulation."""
    global _trial_viz_obj
    
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    
    # Get or create the trial visualization object
    if _trial_viz_obj is None or _trial_viz_obj.Name not in [o.Name for o in doc.Objects]:
        _trial_viz_obj = doc.addObject("Part::Feature", "TrialBounds")
        if hasattr(_trial_viz_obj, "ViewObject"):
            _trial_viz_obj.ViewObject.LineColor = (0.0, 0.5, 1.0)  # Blue
            _trial_viz_obj.ViewObject.LineWidth = 1.5
            _trial_viz_obj.ViewObject.Transparency = 50
    
    try:
        # Get the boundary polygon from the part
        if hasattr(part, 'polygon') and part.polygon:
            # Rotate and translate the polygon to the trial position
            rotated_poly = rotate(part.polygon, angle, origin='centroid')
            translated_poly = translate(rotated_poly, xoff=x, yoff=y)
            
            # Convert shapely polygon to FreeCAD wire
            coords = list(translated_poly.exterior.coords)
            points = [FreeCAD.Vector(c[0], c[1], 0) for c in coords]
            wire = Part.makePolygon(points)
            _trial_viz_obj.Shape = wire
            
            # Force UI update
            QtGui.QApplication.processEvents()
    except Exception as e:
        pass  # Silently ignore drawing errors

def _cleanup_trial_viz():
    """Removes the trial visualization object."""
    global _trial_viz_obj
    if _trial_viz_obj:
        try:
            doc = FreeCAD.ActiveDocument
            if doc and _trial_viz_obj.Name in [o.Name for o in doc.Objects]:
                doc.removeObject(_trial_viz_obj.Name)
        except:
            pass
        _trial_viz_obj = None

# --- Public Function ---
def nest(parts, width, height, rotation_steps=1, simulate=False, **kwargs):
    """Convenience function to run the nesting algorithm."""
    global _trial_viz_obj
    
    # If simulation is enabled, the nester needs the original list of parts
    # that are linked to the visible FreeCAD objects (fc_object).
    # If simulation is disabled, we MUST use a deepcopy to prevent the nester
    # from modifying the original part objects that the controller will use for
    # the final drawing step. This prevents state corruption by ensuring the
    # algorithm works on disposable copies.
    parts_to_process = parts if simulate else copy.deepcopy(parts)

    steps = 0
    sheets = []
    unplaced = []


    if not SHAPELY_AVAILABLE:
        show_shapely_installation_instructions()
        raise NestingDependencyError("The selected algorithm requires the 'Shapely' library, which is not installed.")

    # If simulation is enabled, add trial_callback to kwargs
    if simulate:
        kwargs['trial_callback'] = _draw_trial_bounds

    # The controller now passes a fresh list of all parts to be nested.
    # The nester algorithms are responsible for the full multi-sheet nesting run.
    nester = nesting_strategy.Nester(width, height, rotation_steps, **kwargs)

    # If simulation is enabled, pass a callback that can draw the sheet state.
    if simulate:
        # The callback needs access to the nester's current state.
        nester.update_callback = lambda part, sheet: (sheet.draw(FreeCAD.ActiveDocument, {}, transient_part=part), QtGui.QApplication.processEvents())

    result = nester.nest(parts_to_process)
    
    # Cleanup trial visualization
    if simulate:
        _cleanup_trial_viz()
    
    # Some nesters may return a 3-tuple (sheets, unplaced, steps), while others
    # may return a 2-tuple (sheets, unplaced). We handle both cases here.
    if len(result) == 3:
        sheets, unplaced, steps = result
    else:
        sheets, unplaced = result

    return sheets, unplaced, steps

def show_shapely_installation_instructions():
    msg_box = QtGui.QMessageBox()
    msg_box.setIcon(QtGui.QMessageBox.Warning)
    msg_box.setWindowTitle("Shapely Library Not Found")
    msg_box.setText("The selected nesting algorithm requires the 'Shapely' library, but it is not installed.")
    msg_box.setInformativeText(
        "To use this algorithm, you need to install the 'shapely' library into FreeCAD's Python environment.\n\n"
        "1. **Find FreeCAD's Python Executable:**\n"
        "   Open the Python console in FreeCAD and run:\n"
        "   `import sys; print(sys.executable)`\n"
        "   Copy the path that is printed.\n\n"
        "2. **Open a Command Prompt:**\n"
        "   Open a Windows Command Prompt (cmd.exe).\n\n"
        "3. **Install Shapely:**\n"
        "   In the command prompt, use the path you copied to run the following command (don't forget the quotes):\n"
        "   `\"<path_to_python_exe>\" -m pip install shapely`\n\n"
        "After installation, please restart FreeCAD."
    )
    msg_box.setStandardButtons(QtGui.QMessageBox.Ok)
    msg_box.exec_()
