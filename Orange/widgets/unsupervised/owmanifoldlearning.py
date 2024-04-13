import warnings
from itertools import chain

import numpy as np

from AnyQt.QtWidgets import QWidget, QFormLayout
from AnyQt.QtGui import QFontMetrics
from AnyQt.QtCore import Qt

from Orange.data import Table, Domain, ContinuousVariable
from Orange.data.util import get_unique_names
from Orange.projection import (MDS, Isomap, LocallyLinearEmbedding,
                               SpectralEmbedding, TSNE)
from Orange.projection.manifold import TSNEModel
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import OWWidget, Msg, Input, Output
from Orange.widgets.settings import Setting, SettingProvider
from Orange.widgets import gui


class ManifoldParametersEditor(QWidget, gui.OWComponent):
    def __init__(self, parent):
        QWidget.__init__(self, parent)
        gui.OWComponent.__init__(self, parent)
        self.parameters = {}
        self.parameters_name = {}
        self.parent_callback = parent.settings_changed

        layout = QFormLayout()
        self.setLayout(layout)
        layout.setVerticalSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)

    def get_parameters(self):
        return self.parameters

    def __parameter_changed(self, update_parameter, parameter_name):
        update_parameter(parameter_name)
        self.parent_callback()

    def _create_spin_parameter(self, name, minv, maxv, label):
        self.__spin_parameter_update(name)
        width = QFontMetrics(self.font()).horizontalAdvance("0" * 10)
        control = gui.spin(
            self, self, name, minv, maxv,
            alignment=Qt.AlignRight, callbackOnReturn=True,
            addToLayout=False, controlWidth=width,
            callback=lambda f=self.__spin_parameter_update,
                            p=name: self.__parameter_changed(f, p))
        self.layout().addRow(label, control)

    def __spin_parameter_update(self, name):
        self.parameters[name] = getattr(self, name)

    def _create_combo_parameter(self, name, label):
        self.__combo_parameter_update(name)
        items = (x[1] for x in getattr(self, name + "_values"))
        control = gui.comboBox(
            None, self, name + "_index", items=items,
            callback=lambda f=self.__combo_parameter_update,
                            p=name: self.__parameter_changed(f, p)
        )
        self.layout().addRow(label, control)

    def __combo_parameter_update(self, name):
        index = getattr(self, name + "_index")
        values = getattr(self, name + "_values")
        self.parameters[name] = values[index][0]
        self.parameters_name[name] = values[index][1]

    def _create_radio_parameter(self, name, label):
        self.__radio_parameter_update(name)
        values = (x[1] for x in getattr(self, name + "_values"))
        space = QWidget()
        space.setFixedHeight(4)
        self.layout().addRow(space)
        rbt = gui.radioButtons(
            None, self, name + "_index", btnLabels=values,
            callback=lambda f=self.__radio_parameter_update,
                            p=name: self.__parameter_changed(f, p))
        labox = gui.vBox(None)
        gui.widgetLabel(labox, label)
        gui.rubber(labox)
        self.layout().addRow(labox, rbt)

    def __radio_parameter_update(self, name):
        index = getattr(self, name + "_index")
        values = getattr(self, name + "_values")
        self.parameters[name] = values[index][0]
        self.parameters_name[name] = values[index][1]


class TSNEParametersEditor(ManifoldParametersEditor):
    _metrics = ("euclidean", "manhattan", "chebyshev", "jaccard")
    metric_index = Setting(0)
    metric_values = [("euclidean", "欧氏"), ("manhattan", "曼哈顿"),
                     ("chebyshev", "切比雄夫"), ("jaccard", "杰卡德")]

    perplexity = Setting(30)
    early_exaggeration = Setting(12)
    learning_rate = Setting(200)
    n_iter = Setting(1000)

    initialization_index = Setting(0)
    initialization_values = [("pca", "PCA"), ("random", "随机")]

    def __init__(self, parent):
        super().__init__(parent)
        self._create_combo_parameter("metric", "Metric:")
        self._create_spin_parameter("perplexity", 1, 100, "Perplexity:")
        self._create_spin_parameter("early_exaggeration", 1, 100,
                                    "Early exaggeration:")
        self._create_spin_parameter("learning_rate", 1, 1000, "Learning rate:")
        self._create_spin_parameter("n_iter", 250, 10000, "Max iterations:")
        self._create_radio_parameter("initialization", "Initialization:")

    def get_report_parameters(self):
        return {"度量": self.parameters_name["metric"],
                "困惑度": self.parameters["perplexity"],
                "早期夸张": self.parameters["early_exaggeration"],
                "学习率": self.parameters["learning_rate"],
                "最大迭代次数": self.parameters["n_iter"],
                "初始化": self.parameters_name["initialization"]}

class MDSParametersEditor(ManifoldParametersEditor):
    max_iter = Setting(300)
    init_type_index = Setting(0)
    init_type_values = (("PCA", "PCA (Torgerson)"),
                        ("random", "随机"))

    def __init__(self, parent):
        super().__init__(parent)
        self._create_spin_parameter("max_iter", 10, 10 ** 4, "Max iterations:")
        self._create_radio_parameter("init_type", "Initialization:")

    def get_parameters(self):
        par = super().get_parameters()
        if self.init_type_index == 0:
            par = {"n_init": 1, **par}
        return par

    def get_report_parameters(self):
        return {"最大迭代次数  ": self.parameters["max_iter"],
                "初始化": self.parameters_name["init_type"]}

class IsomapParametersEditor(ManifoldParametersEditor):
    n_neighbors = Setting(5)

    def __init__(self, parent):
        super().__init__(parent)
        self._create_spin_parameter("n_neighbors", 1, 10 ** 2, "Neighbors:")

    def get_report_parameters(self):
        return {"邻居数": self.parameters["n_neighbors"]}

class LocallyLinearEmbeddingParametersEditor(ManifoldParametersEditor):
    n_neighbors = Setting(5)
    max_iter = Setting(100)
    method_index = Setting(0)
    method_values = (("standard", "标准"),
                     ("modified", "修正"),
                     ("hessian", "Hessian 特征映射"),
                     ("ltsa", "局部"))

    def __init__(self, parent):
        super().__init__(parent)
        self._create_combo_parameter("method", "Method:")
        self._create_spin_parameter("n_neighbors", 1, 10 ** 2, "Neighbors:")
        self._create_spin_parameter("max_iter", 10, 10 ** 4, "Max iterations:")

    def get_report_parameters(self):
        return {"方法": self.parameters_name["method"],
                "邻居数": self.parameters["n_neighbors"],
                "最大迭代次数": self.parameters["max_iter"]}

class SpectralEmbeddingParametersEditor(ManifoldParametersEditor):
    affinity_index = Setting(0)
    affinity_values = (("nearest_neighbors", "最近邻"),
                       ("rbf", "RBF 核"))

    def __init__(self, parent):
        super().__init__(parent)
        self._create_combo_parameter("affinity", "Affinity:")

    def get_report_parameters(self):
        return {"亲和性": self.parameters_name["affinity"]}

class OWManifoldLearning(OWWidget):
    name = "流形学习 Manifold Learning"
    description = "非线性降维。"
    icon = "icons/Manifold.svg"
    priority = 2200
    keywords = "manifold learning"
    settings_version = 2

    class Inputs:
        data = Input("数据", Table)

    class Outputs:
        transformed_data = Output("转换后的数据", Table, dynamic=False,
                                  replaces=["转换后的数据"])

    MANIFOLD_METHODS = (TSNE, MDS, Isomap, LocallyLinearEmbedding,
                        SpectralEmbedding)

    tsne_editor = SettingProvider(TSNEParametersEditor)
    mds_editor = SettingProvider(MDSParametersEditor)
    isomap_editor = SettingProvider(IsomapParametersEditor)
    lle_editor = SettingProvider(LocallyLinearEmbeddingParametersEditor)
    spectral_editor = SettingProvider(SpectralEmbeddingParametersEditor)

    resizing_enabled = False
    want_main_area = False

    manifold_method_index = Setting(0)
    n_components = Setting(2)
    auto_apply = Setting(True)

    class Error(OWWidget.Error):
        n_neighbors_too_small = Msg("对于选择的方法和分量,"
                                    "邻居数必须大于 {}")
        manifold_error = Msg("{}")
        sparse_not_supported = Msg("不支持稀疏数据。")
        out_of_memory = Msg("内存不足")

    class Warning(OWWidget.Warning):
        graph_not_connected = Msg("图不连通,嵌入可能无效")

    @classmethod
    def migrate_settings(cls, settings, version):
        if version < 2:
            tsne_settings = settings.get('tsne_editor', {})
            # Fixup initialization index
            if 'init_index' in tsne_settings:
                idx = tsne_settings.pop('init_index')
                idx = min(idx, len(TSNEParametersEditor.initialization_values))
                tsne_settings['initialization_index'] = idx
            # We removed several metrics here
            if 'metric_index' in tsne_settings:
                idx = tsne_settings['metric_index']
                idx = min(idx, len(TSNEParametersEditor.metric_values))
                tsne_settings['metric_index'] = idx

    def __init__(self):
        self.data = None

        # GUI
        method_box = gui.vBox(self.controlArea, "方法")
        self.manifold_methods_combo = gui.comboBox(
            method_box, self, "manifold_method_index",
            items=[m.name for m in self.MANIFOLD_METHODS],
            callback=self.manifold_method_changed)

        self.params_box = gui.vBox(method_box)

        self.tsne_editor = TSNEParametersEditor(self)
        self.mds_editor = MDSParametersEditor(self)
        self.isomap_editor = IsomapParametersEditor(self)
        self.lle_editor = LocallyLinearEmbeddingParametersEditor(self)
        self.spectral_editor = SpectralEmbeddingParametersEditor(self)
        self.parameter_editors = [
            self.tsne_editor, self.mds_editor, self.isomap_editor,
            self.lle_editor, self.spectral_editor]

        for editor in self.parameter_editors:
            self.params_box.layout().addWidget(editor)
            editor.hide()
        self.params_widget = self.parameter_editors[self.manifold_method_index]
        self.params_widget.show()

        output_box = gui.vBox(self.controlArea, "输出")
        self.n_components_spin = gui.spin(
            output_box, self, "n_components", 1, 10, label="Components:",
            controlWidth=QFontMetrics(self.font()).horizontalAdvance("0" * 10),
            alignment=Qt.AlignRight, callbackOnReturn=True,
            callback=self.settings_changed)
        gui.rubber(self.n_components_spin.box)
        self.apply_button = gui.auto_apply(self.buttonsArea, self)

    def manifold_method_changed(self):
        self.params_widget.hide()
        self.params_widget = self.parameter_editors[self.manifold_method_index]
        self.params_widget.show()
        self.commit.deferred()

    def settings_changed(self):
        self.commit.deferred()

    @Inputs.data
    def set_data(self, data):
        self.data = data
        self.n_components_spin.setMaximum(len(self.data.domain.attributes)
                                          if self.data else 10)
        self.commit.now()

    @gui.deferred
    def commit(self):
        builtin_warn = warnings.warn

        def _handle_disconnected_graph_warning(msg, *args, **kwargs):
            if msg.startswith("图不完全连通"):
                self.Warning.graph_not_connected()
            else:
                builtin_warn(msg, *args, **kwargs)

        out = None
        data = self.data
        method = self.MANIFOLD_METHODS[self.manifold_method_index]
        have_data = data is not None and len(data)
        self.Error.clear()
        self.Warning.clear()

        if have_data and data.is_sparse():
            self.Error.sparse_not_supported()
        elif have_data:
            names = [var.name for var in chain(data.domain.class_vars,
                                               data.domain.metas) if var]
            proposed = ["C{}".format(i) for i in range(self.n_components)]
            unique = get_unique_names(names, proposed)
            domain = Domain([ContinuousVariable(name) for name in unique],
                            data.domain.class_vars,
                            data.domain.metas)
            try:
                warnings.warn = _handle_disconnected_graph_warning
                projector = method(**self.get_method_parameters(data, method))
                model = projector(data)
                if isinstance(model, TSNEModel):
                    out = model.embedding
                else:
                    X = model.embedding_
                    out = Table(domain, X, data.Y, data.metas)
            except ValueError as e:
                if e.args[0] == "for method='hessian', n_neighbors " \
                                "must be greater than [n_components" \
                                " * (n_components + 3) / 2]":
                    n = self.n_components * (self.n_components + 3) / 2
                    self.Error.n_neighbors_too_small("{}".format(n))
                else:
                    self.Error.manifold_error(e.args[0])
            except MemoryError:
                self.Error.out_of_memory()
            except np.linalg.linalg.LinAlgError as e:
                self.Error.manifold_error(str(e))
            finally:
                warnings.warn = builtin_warn

        self.Outputs.transformed_data.send(out)

    def get_method_parameters(self, data, method):
        parameters = dict(n_components=self.n_components)
        parameters.update(self.params_widget.get_parameters())
        return parameters

    def send_report(self):
        method = self.MANIFOLD_METHODS[self.manifold_method_index]
        self.report_items((("方法", method.name),))
        parameters = {"分量数 ": self.n_components}
        parameters.update(self.params_widget.get_report_parameters())
        self.report_items("方法参数", parameters)
        if self.data:
            self.report_data("数据  ", self.data)


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWManifoldLearning).run(Table("brown-selected"))
