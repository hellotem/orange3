# pylint: disable=too-many-ancestors
from enum import IntEnum
from types import SimpleNamespace as namespace

import numpy as np

from AnyQt.QtCore import Qt, QRectF, QLineF, QPoint
from AnyQt.QtGui import QPalette, QFontMetrics
from AnyQt.QtWidgets import QSizePolicy

import pyqtgraph as pg

from Orange.data import Table, Domain
from Orange.projection import FreeViz
from Orange.projection.freeviz import FreeVizModel
from Orange.widgets import widget, gui, settings
from Orange.widgets.utils.concurrent import ConcurrentWidgetMixin, TaskState
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.visualize.utils.component import OWGraphWithAnchors
from Orange.widgets.visualize.utils.plotutils import AnchorItem
from Orange.widgets.visualize.utils.widget import OWAnchorProjectionWidget


class Result(namespace):
    projector = None  # type: FreeViz
    projection = None  # type: FreeVizModel


MAX_ITERATIONS = 1000


def run_freeviz(data: Table, projector: FreeViz, state: TaskState):
    res = Result(projector=projector, projection=None)
    step, steps = 0, MAX_ITERATIONS
    initial = res.projector.components_.T
    state.set_status("计算中...")
    while True:
        # Needs a copy because projection should not be modified inplace.
        # If it is modified inplace, the widget and the thread hold a
        # reference to the same object. When the thread is interrupted it
        # is still modifying the object, but the widget receives it
        # (the modified object) with a delay.
        res.projection = res.projector(data).copy()
        anchors = res.projector.components_.T
        res.projector.initial = anchors

        state.set_partial_result(res)
        if np.allclose(initial, anchors, rtol=1e-5, atol=1e-4):
            return res
        initial = anchors

        step += 1
        state.set_progress_value(100 * step / steps)
        if state.is_interruption_requested():
            return res


class OWFreeVizGraph(OWGraphWithAnchors):
    hide_radius = settings.Setting(0)

    @property
    def scaled_radius(self):
        return self.hide_radius / 100 + 1e-5

    def update_radius(self):
        self.update_circle()
        self.update_anchors()

    def set_view_box_range(self):
        self.view_box.setRange(QRectF(-1.05, -1.05, 2.1, 2.1))

    def closest_draggable_item(self, pos):
        points, *_ = self.master.get_anchors()
        if points is None or not len(points):
            return None
        mask = np.linalg.norm(points, axis=1) > self.scaled_radius
        xi, yi = points[mask].T
        distances = (xi - pos.x()) ** 2 + (yi - pos.y()) ** 2
        if len(distances) and np.min(distances) < self.DISTANCE_DIFF ** 2:
            return np.flatnonzero(mask)[np.argmin(distances)]
        return None

    def update_anchors(self):
        points, labels = self.master.get_anchors()
        if points is None:
            return
        r = self.scaled_radius
        if self.anchor_items is None:
            self.anchor_items = []
            for point, label in zip(points, labels):
                anchor = AnchorItem(line=QLineF(0, 0, *point), text=label)
                anchor.setVisible(bool(np.linalg.norm(point) > r))
                anchor.setPen(pg.mkPen((100, 100, 100)))
                anchor.setFont(self.parameter_setter.anchor_font)
                self.plot_widget.addItem(anchor)
                self.anchor_items.append(anchor)
        else:
            for anchor, point, label in zip(self.anchor_items, points, labels):
                anchor.setLine(QLineF(0, 0, *point))
                anchor.setText(label)
                anchor.setVisible(bool(np.linalg.norm(point) > r))
                anchor.setFont(self.parameter_setter.anchor_font)

    def update_circle(self):
        super().update_circle()
        if self.circle_item is not None:
            r = self.scaled_radius
            self.circle_item.setRect(QRectF(-r, -r, 2 * r, 2 * r))
            color = self.plot_widget.palette().color(QPalette.Disabled, QPalette.Text)
            pen = pg.mkPen(color, width=1, cosmetic=True)
            self.circle_item.setPen(pen)

    def _add_indicator_item(self, anchor_idx):
        x, y = self.anchor_items[anchor_idx].get_xy()
        dx = (self.view_box.childGroup.mapToDevice(QPoint(1, 0)) -
              self.view_box.childGroup.mapToDevice(QPoint(-1, 0))).x()
        self.indicator_item = MoveIndicator(x, y, 600 / dx)
        self.plot_widget.addItem(self.indicator_item)


class InitType(IntEnum):
    Circular, Random = 0, 1

    @staticmethod
    def items():
        return ["环形", "随机"]


class OWFreeViz(OWAnchorProjectionWidget, ConcurrentWidgetMixin):
    MAX_INSTANCES = 10000

    name = "FreeViz"
    description = "显示 FreeViz 投影"
    icon = "icons/Freeviz.svg"
    priority = 240
    keywords = "freeviz, viz"

    settings_version = 3
    initialization = settings.Setting(InitType.Circular)
    balance = settings.Setting(False)
    gravity_index = settings.Setting(4)
    GRAPH_CLASS = OWFreeVizGraph
    graph = settings.SettingProvider(OWFreeVizGraph)

    GravityValues = [0.1, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5]

    class Error(OWAnchorProjectionWidget.Error):
        no_class_var = widget.Msg("数据必须有目标变量")
        multiple_class_vars = widget.Msg(
            "数据必须有单个目标变量")
        not_enough_class_vars = widget.Msg(
            "目标变量必须至少有两个唯一值")
        features_exceeds_instances = widget.Msg(
            "特征数超过实例数")
        too_many_data_instances = widget.Msg("数据太大")
        constant_data = widget.Msg("所有数据列都是常数")
        not_enough_features = widget.Msg("至少需要两个特征")

    class Warning(OWAnchorProjectionWidget.Warning):
        removed_features = widget.Msg("分类特征值数量超过"
                                      " 两个值时不显示")

    def __init__(self):
        OWAnchorProjectionWidget.__init__(self)
        ConcurrentWidgetMixin.__init__(self)
        self.__optimized = False

    def _add_controls(self):
        self.__add_controls_start_box()
        super()._add_controls()
        self.gui.add_control(
            self._effects_box, gui.hSlider, "Hide radius:", master=self.graph,
            value="hide_radius", minValue=0, maxValue=100, step=10,
            createLabel=False, callback=self.__radius_slider_changed
        )

    def __add_controls_start_box(self):
        box = gui.vBox(self.controlArea, box="优化", spacing=0)
        gui.comboBox(
            box, self, "initialization", label="Initialization:",
            items=InitType.items(), orientation=Qt.Horizontal,
            callback=self.__init_combo_changed,
            sizePolicy=(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        )
        box2 = gui.hBox(box)
        gui.checkBox(
            box2, self, "balance", "重力",
            callback=self.__gravity_changed)
        self.grav_slider = gui.hSlider(
            box2, self, "gravity_index",
            minValue=0, maxValue=len(self.GravityValues) - 1,
            callback=self.__gravity_dragged, createLabel=False)
        self.gravity_label = gui.widgetLabel(box2)
        self.gravity_label.setFixedWidth(
            max(QFontMetrics(self.font()).horizontalAdvance(str(x))
                for x in self.GravityValues))
        self.gravity_label.setAlignment(Qt.AlignRight)
        self.__update_gravity_label()
        self.run_button = gui.button(box, self, "开始", self._toggle_run)

    @property
    def effective_variables(self):
        return [a for a in self.data.domain.attributes
                if a.is_continuous or a.is_discrete and len(a.values) == 2]

    @property
    def effective_data(self):
        return self.data.transform(Domain(self.effective_variables,
                                          self.data.domain.class_vars))

    def __gravity_dragged(self):
        self.balance = True
        self.__gravity_changed()

    def __update_gravity_label(self):
        self.gravity_label.setText(str(self.GravityValues[self.gravity_index]))

    def __gravity_changed(self):
        gravity = self.GravityValues[self.gravity_index]
        if self.projector is not None:
            self.projector.gravity = gravity if self.balance else None
        self.__update_gravity_label()
        if self.task is None and self.__optimized:
            self._run()

    def __radius_slider_changed(self):
        self.graph.update_radius()

    def __init_combo_changed(self):
        self.Error.proj_error.clear()
        self.init_projection()
        self.setup_plot()
        self.commit.deferred()
        if self.task is not None:
            self._run()

    def _toggle_run(self):
        if self.task is not None:
            self.cancel()
            self.graph.set_sample_size(None)
            self.run_button.setText("恢复")
            self.commit.deferred()
        else:
            self._run()

    def _run(self):
        if self.data is None:
            return
        self.graph.set_sample_size(self.SAMPLE_SIZE)
        self.run_button.setText("停止")
        self.start(run_freeviz, self.effective_data, self.projector)

    # ConcurrentWidgetMixin
    def on_partial_result(self, result: Result):
        assert isinstance(result.projector, FreeViz)
        assert isinstance(result.projection, FreeVizModel)
        self.projector = result.projector
        self.projection = result.projection
        self.graph.update_coordinates()
        self.graph.update_density()

    def on_done(self, result: Result):
        assert isinstance(result.projector, FreeViz)
        assert isinstance(result.projection, FreeVizModel)
        self.projector = result.projector
        self.projection = result.projection
        self.graph.set_sample_size(None)
        self.run_button.setText("开始")
        self.__optimized = True
        self.commit.deferred()

    def on_exception(self, ex: Exception):
        self.Error.proj_error(ex)
        self.graph.set_sample_size(None)
        self.run_button.setText("开始 ")

    # OWAnchorProjectionWidget
    @OWAnchorProjectionWidget.Inputs.data
    def set_data(self, data):
        super().set_data(data)
        self.graph.set_sample_size(None)
        if self._invalidated:
            self.init_projection()

    def init_projection(self):
        if self.data is None:
            return
        anchors = FreeViz.init_radial(len(self.effective_variables)) \
            if self.initialization == InitType.Circular \
            else FreeViz.init_random(len(self.effective_variables), 2)
        if self.balance:
            gravity = self.GravityValues[self.gravity_index]
        else:
            gravity = None
        self.projector = FreeViz(scale=False, center=False,
                                 initial=anchors, maxiter=10, gravity=gravity)
        data = self.projector.preprocess(self.effective_data)
        self.projector.domain = data.domain
        self.projector.components_ = anchors.T
        self.projection = FreeVizModel(self.projector, self.projector.domain, 2)
        self.projection.pre_domain = data.domain
        self.projection.name = self.projector.name
        self.__optimized = False

    def check_data(self):
        def error(err):
            err()
            self.data = None

        super().check_data()
        if self.data is not None:
            class_vars, domain = self.data.domain.class_vars, self.data.domain
            if not class_vars:
                error(self.Error.no_class_var)
            elif len(class_vars) > 1:
                error(self.Error.multiple_class_vars)
            elif class_vars[0].is_discrete and len(np.unique(self.data.Y)) < 2:
                error(self.Error.not_enough_class_vars)
            elif len(self.data.domain.attributes) < 2:
                error(self.Error.not_enough_features)
            elif len(self.data.domain.attributes) > self.data.X.shape[0]:
                error(self.Error.features_exceeds_instances)
            elif not np.sum(np.std(self.data.X, axis=0)):
                error(self.Error.constant_data)
            elif np.sum(np.all(np.isfinite(self.data.X), axis=1)) > self.MAX_INSTANCES:
                error(self.Error.too_many_data_instances)
            else:
                if len(self.effective_variables) < len(domain.attributes):
                    self.Warning.removed_features()

    def enable_controls(self):
        super().enable_controls()
        self.run_button.setEnabled(self.data is not None)
        self.run_button.setText("开始")

    def get_coordinates_data(self):
        embedding = self.get_embedding()
        if embedding is None:
            return None, None
        valid_emb = embedding[self.valid_data]
        return valid_emb.T / (np.max(np.linalg.norm(valid_emb, axis=1)) or 1)

    def _manual_move(self, anchor_idx, x, y):
        self.projector.initial[anchor_idx] = [x, y]
        super()._manual_move(anchor_idx, x, y)

    def clear(self):
        super().clear()
        self.cancel()

    def onDeleteWidget(self):
        self.shutdown()
        super().onDeleteWidget()

    @classmethod
    def migrate_settings(cls, _settings, version):
        if version < 3:
            if "radius" in _settings:
                _settings["graph"]["hide_radius"] = _settings["radius"]

    @classmethod
    def migrate_context(cls, context, version):
        if version < 3:
            values = context.values
            values["attr_color"] = values["graph"]["attr_color"]
            values["attr_size"] = values["graph"]["attr_size"]
            values["attr_shape"] = values["graph"]["attr_shape"]
            values["attr_label"] = values["graph"]["attr_label"]


class MoveIndicator(pg.GraphicsObject):
    def __init__(self, x, y, scene_size, parent=None):
        super().__init__(parent)
        self.arrows = [
            pg.ArrowItem(pos=(x - scene_size * 0.07 * np.cos(np.radians(ang)),
                              y + scene_size * 0.07 * np.sin(np.radians(ang))),
                         parent=self, angle=ang,
                         headLen=13, tipAngle=45,
                         brush=pg.mkColor(128, 128, 128))
            for ang in (0, 90, 180, 270)]

    def paint(self, painter, option, widget):
        pass

    def boundingRect(self):
        return QRectF()


if __name__ == "__main__":  # pragma: no cover
    table = Table("zoo")
    WidgetPreview(OWFreeViz).run(set_data=table, set_subset_data=table[::10])
