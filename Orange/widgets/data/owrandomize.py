import random

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QSizePolicy

from Orange.data import Table
from Orange.preprocess import Randomize
from Orange.widgets.settings import Setting
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets import gui


class OWRandomize(OWWidget):
    name = "随机化 Randomize"
    description = "随机化数据表中的特征、类和/或元数据。"
    category = "变换"
    icon = "icons/Random.svg"
    priority = 2200
    keywords = "随机化,随机"

    class Inputs:
        data = Input("数据", Table)

    class Outputs:
        data = Output("数据", Table)

    resizing_enabled = False
    want_main_area = False

    shuffle_class = Setting(True)
    shuffle_attrs = Setting(False)
    shuffle_metas = Setting(False)
    scope_prop = Setting(80)
    random_seed = Setting(False)
    auto_apply = Setting(True)

    def __init__(self):
        super().__init__()
        self.data = None

        # GUI
        box = gui.hBox(self.controlArea, "随机列")
        box.layout().setSpacing(20)
        self.class_check = gui.checkBox(
            box, self, "shuffle_class", "类",
            callback=self._shuffle_check_changed)
        self.attrs_check = gui.checkBox(
            box, self, "shuffle_attrs", "特征",
            callback=self._shuffle_check_changed)
        self.metas_check = gui.checkBox(
            box, self, "shuffle_metas", "元数据",
            callback=self._shuffle_check_changed)

        box = gui.vBox(self.controlArea, "随机行")
        hbox = gui.hBox(box)
        gui.widgetLabel(hbox, "无")
        self.scope_slider = gui.hSlider(
            hbox, self, "scope_prop", minValue=0, maxValue=100, width=140,
            createLabel=False, callback=self._scope_slider_changed)
        gui.widgetLabel(hbox, "全部")
        self.scope_label = gui.widgetLabel(
            box, "", alignment=Qt.AlignCenter,
            sizePolicy=(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed))
        self._set_scope_label()
        self.replicable_check = gui.checkBox(
            box, self, "random_seed", "可复制的随机化",
            callback=self._shuffle_check_changed)

        gui.auto_apply(self.buttonsArea, self)

    @property
    def parts(self):
        return [self.shuffle_class, self.shuffle_attrs, self.shuffle_metas]

    def _shuffle_check_changed(self):
        self.commit.deferred()

    def _scope_slider_changed(self):
        self._set_scope_label()
        self.commit.deferred()

    def _set_scope_label(self):
        self.scope_label.setText("{}%".format(self.scope_prop))

    @Inputs.data
    def set_data(self, data):
        self.data = data
        self.commit.now()

    @gui.deferred
    def commit(self):
        data = None
        if self.data:
            rand_seed = self.random_seed or None
            size = int(len(self.data) * self.scope_prop / 100)
            random.seed(rand_seed)
            indices = sorted(random.sample(range(len(self.data)), size))
            type_ = sum(t for t, p in zip(Randomize.Type, self.parts) if p)
            randomized = Randomize(type_, rand_seed)(self.data[indices])
            data = self.data.copy()
            with data.unlocked():
                for i, instance in zip(indices, randomized):
                    data[i] = instance
        self.Outputs.data.send(data)

    def send_report(self):
        labels = ["类", "特征", "元数据"]
        include = [label for label, i in zip(labels, self.parts) if i]
        text = "无" if not include else \
            " 和 ".join(filter(None, (", ".join(include[:-1]), include[-1])))
        self.report_items(
            "设置",
            [("随机列", text),
             ("随机行的比例", "{}%".format(self.scope_prop)),
             ("可复制", "是" if self.random_seed else "否")])


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWRandomize).run(Table("iris"))
