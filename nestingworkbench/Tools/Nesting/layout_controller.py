# Nesting/nesting/layout_controller.py

"""
This module contains the LayoutController class, which is responsible for managing
and drawing a complete nesting layout, including both final and preview states.
"""


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

    def calculate_sheet_fills(self):
        """Calculates the fill percentage for each sheet in the layout."""
        return [sheet.calculate_fill_percentage() for sheet in self.sheets]

    def execute(self, fp):
        """This method is called on recompute, but is no longer used for drawing."""
        pass

    @property
    def doc(self):
        return self.obj.Document
