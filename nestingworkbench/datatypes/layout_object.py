# Nesting/nestingworkbench/datatypes/layout_object.py

"""
This module defines a custom FreeCAD scripted object for representing a full nesting layout.
"""

import FreeCAD
from ..Tools.Nesting.layout_controller import LayoutController

class ViewProviderLayout:
    """A view provider for the LayoutObject."""

    def __init__(self, vobj):
        """Called when the view object is created."""
        vobj.Proxy = self

    def getIcon(self):
        """Return the icon for the layout object in the tree view."""
        # You can create a specific icon for layouts later if you wish
        return """
            /* XPM */
            static char * layout_icon_xpm[] = {
            "16 16 2 1", " 	c None", ".	c #000000",
            "................", ".              .", ". ............ .", ". .          . .",
            ". . ........ . .", ". . .      . . .", ". . .      . . .", ". . .      . . .",
            ". . ........ . .", ". .          . .", ". ............ .", ".              .",
            "................", "................", "................", "................"};
            """

def create_layout_object(name="Layout"):
    """Helper function to create a new LayoutObject in the active document."""
    obj = FreeCAD.ActiveDocument.addObject("App::DocumentObjectGroupPython", name)
    LayoutController(obj) # The controller is now the proxy
    if FreeCAD.GuiUp:
        ViewProviderLayout(obj.ViewObject)
    return obj