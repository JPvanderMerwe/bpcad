"""
Interactive 3D: rotate, pan, zoom a real solid rather than look at a PNG.

VTK 9.6 rendering into a Qt widget. VTK arrives with CadQuery, so this is not a
new dependency - it is one that was already sitting there unused.

WHAT THIS IS NOT
----------------
It is not a replacement for the height map. A shaded view - here or anywhere -
cannot show a recess whose floor faces the same way as the surface around it,
because both take the same light. That is why render/ still produces the height
map on the CPU and why the report still points you at it. This view is for
turning a part over and seeing its shape; the height map is for checking that
the shape is right.

The colour-by-height mode below is the exception, and it exists precisely so
you can get that check interactively too.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QVBoxLayout, QWidget

from bpcad.gui.theme import VIEWPORT_BG

# The same six named directions as render.views, so "3q" means the same thing
# whether you are looking at the live view or the rendered PNG.
VIEW_DIRECTIONS = {
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "above": (0.0, 0.0, 1.0),
    "below": (0.0, 0.0, -1.0),
    "3q": (0.64, -0.64, 0.42),
}

# Distinct hues for the separate bodies of a print-in-place assembly. Six is
# enough for the vent's frame, four blades and tie bar; it wraps beyond that.
BODY_COLOURS = [
    (0.62, 0.66, 0.72), (0.30, 0.66, 0.85), (0.90, 0.62, 0.32),
    (0.42, 0.80, 0.55), (0.82, 0.52, 0.78), (0.88, 0.78, 0.40),
]


class Viewer3D(QWidget):
    """A VTK render window in a Qt widget, showing one mesh."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ok = False
        self._actors: list = []
        self._path: Path | None = None
        self._mode = "shaded"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            from vtkmodules.qt.QVTKRenderWindowInteractor import (
                QVTKRenderWindowInteractor,
            )
            import vtkmodules.all as vtk

            self._vtk = vtk
            self._widget = QVTKRenderWindowInteractor(self)
            layout.addWidget(self._widget)

            self._renderer = vtk.vtkRenderer()
            self._renderer.SetBackground(*VIEWPORT_BG)
            self._renderer.SetBackground2(
                min(VIEWPORT_BG[0] + 0.05, 1.0),
                min(VIEWPORT_BG[1] + 0.05, 1.0),
                min(VIEWPORT_BG[2] + 0.06, 1.0),
            )
            self._renderer.GradientBackgroundOn()

            self._widget.GetRenderWindow().AddRenderer(self._renderer)
            self._interactor = self._widget.GetRenderWindow().GetInteractor()
            style = vtk.vtkInteractorStyleTrackballCamera()
            self._interactor.SetInteractorStyle(style)
            self._ok = True
        except Exception as exc:                       # pragma: no cover - env
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QLabel

            label = QLabel(
                "Interactive 3D is unavailable in this environment.\n\n%s\n\n"
                "The rendered views and the height map still work - they are "
                "produced on the CPU and need no graphics driver." % exc
            )
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)

    # -- lifecycle ---------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._ok

    def start(self) -> None:
        """Must be called once the widget is on screen, not before."""
        if self._ok:
            self._interactor.Initialize()

    def shutdown(self) -> None:
        """VTK holds a native window and will complain loudly if it is not told."""
        if self._ok:
            try:
                self._widget.GetRenderWindow().Finalize()
                self._interactor.TerminateApp()
            except Exception:
                pass

    # -- content -----------------------------------------------------------

    def clear(self) -> None:
        if not self._ok:
            return
        for actor in self._actors:
            self._renderer.RemoveActor(actor)
        self._actors.clear()
        self._path = None
        self._widget.GetRenderWindow().Render()

    def load(self, stl_path: str | Path, mode: str | None = None) -> bool:
        """
        Show an STL, one colour per separate body.

        Colouring the bodies apart is not decoration: a print-in-place mechanism
        is meant to come off the bed as six loose pieces, and if a boolean has
        silently fused two of them the picture says so immediately.
        """
        if not self._ok:
            return False
        path = Path(stl_path)
        if not path.is_file():
            return False

        self.clear()
        self._path = path
        self._mode = mode or self._mode
        vtk = self._vtk

        reader = vtk.vtkSTLReader()
        reader.SetFileName(str(path))
        reader.Update()

        connectivity = vtk.vtkPolyDataConnectivityFilter()
        connectivity.SetInputConnection(reader.GetOutputPort())
        connectivity.SetExtractionModeToAllRegions()
        connectivity.Update()
        n_bodies = max(1, connectivity.GetNumberOfExtractedRegions())

        if self._mode == "height":
            self._add_height_mapped(reader)
        elif n_bodies > 1:
            self._add_bodies(connectivity, n_bodies)
        else:
            self._add_single(reader, BODY_COLOURS[0])

        self._add_lighting()
        self.set_view("3q")
        return True

    def _add_single(self, source, colour) -> None:
        vtk = self._vtk
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(source.GetOutputPort())
        normals.SplittingOff()
        normals.ConsistencyOn()
        normals.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*colour)
        prop.SetSpecular(0.28)
        prop.SetSpecularPower(24)
        prop.SetAmbient(0.22)
        prop.SetDiffuse(0.78)
        self._renderer.AddActor(actor)
        self._actors.append(actor)

    def _add_bodies(self, connectivity, n_bodies: int) -> None:
        vtk = self._vtk
        for i in range(n_bodies):
            part = vtk.vtkPolyDataConnectivityFilter()
            part.SetInputConnection(connectivity.GetInputConnection(0, 0))
            part.SetExtractionModeToSpecifiedRegions()
            part.InitializeSpecifiedRegionList()
            part.AddSpecifiedRegion(i)
            part.Update()

            clean = vtk.vtkCleanPolyData()
            clean.SetInputConnection(part.GetOutputPort())
            self._add_single(clean, BODY_COLOURS[i % len(BODY_COLOURS)])

    def _add_height_mapped(self, source) -> None:
        """
        Colour by height along Z, the interactive twin of the height map.

        Same purpose as the PNG: a recess whose floor shares a normal with the
        surface around it is invisible under shading and obvious under colour.
        """
        vtk = self._vtk
        elevation = vtk.vtkElevationFilter()
        elevation.SetInputConnection(source.GetOutputPort())
        bounds = source.GetOutput().GetBounds()
        elevation.SetLowPoint(0, 0, bounds[4])
        elevation.SetHighPoint(0, 0, bounds[5])
        elevation.Update()

        lut = vtk.vtkLookupTable()
        lut.SetHueRange(0.68, 0.0)
        lut.SetSaturationRange(0.85, 0.95)
        lut.SetValueRange(0.35, 1.0)
        lut.Build()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(elevation.GetOutputPort())
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(bounds[4], bounds[5])

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetAmbient(0.45)
        actor.GetProperty().SetDiffuse(0.55)
        self._renderer.AddActor(actor)
        self._actors.append(actor)

    def _add_lighting(self) -> None:
        """
        Light over the camera's shoulder, so it follows the view.

        A fixed light leaves faces black as you orbit, which reads as a hole in
        the geometry that is not there.
        """
        vtk = self._vtk
        self._renderer.RemoveAllLights()
        key = vtk.vtkLight()
        key.SetLightTypeToCameraLight()
        key.SetPosition(-0.4, 0.5, 1.0)
        key.SetIntensity(0.95)
        fill = vtk.vtkLight()
        fill.SetLightTypeToCameraLight()
        fill.SetPosition(0.7, -0.3, 0.6)
        fill.SetIntensity(0.35)
        self._renderer.AddLight(key)
        self._renderer.AddLight(fill)

    # -- camera ------------------------------------------------------------

    def set_view(self, name: str) -> None:
        if not self._ok or name not in VIEW_DIRECTIONS:
            return
        dx, dy, dz = VIEW_DIRECTIONS[name]
        camera = self._renderer.GetActiveCamera()
        camera.SetPosition(dx, dy, dz)
        camera.SetFocalPoint(0, 0, 0)
        camera.SetViewUp(0, 0, 1) if abs(dz) < 0.99 else camera.SetViewUp(0, 1, 0)
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()
        self._widget.GetRenderWindow().Render()

    def set_mode(self, mode: str) -> None:
        """"shaded" or "height". Reloads, because the pipeline differs."""
        if mode == self._mode:
            return
        self._mode = mode
        if self._path is not None:
            self.load(self._path, mode=mode)

    @property
    def mode(self) -> str:
        return self._mode

    def reset_camera(self) -> None:
        if self._ok:
            self._renderer.ResetCamera()
            self._widget.GetRenderWindow().Render()
