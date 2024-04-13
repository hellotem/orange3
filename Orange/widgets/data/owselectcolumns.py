from functools import partial
from typing import Optional, Dict, Tuple

from AnyQt.QtCore import (
    Qt, QTimer, QSortFilterProxyModel, QItemSelection, QItemSelectionModel,
    QMimeData, QAbstractItemModel
)
from AnyQt.QtGui import QDrag, QDropEvent
from AnyQt.QtWidgets import QWidget, QGridLayout, QListView

from Orange.data import Domain, Variable
from Orange.widgets import gui, widget
from Orange.widgets.settings import (
    ContextSetting, Setting, DomainContextHandler
)
from Orange.widgets.utils import vartype
from Orange.widgets.utils.listfilter import (
    VariablesListItemView, slices, variables_filter
)
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Input, Output, AttributeList, Msg
from Orange.data.table import Table
from Orange.widgets.utils.itemmodels import VariableListModel
import Orange


def source_model(view):
    """ Return the source model for the Qt Item View if it uses
    the QSortFilterProxyModel.
    """
    if isinstance(view.model(), QSortFilterProxyModel):
        return view.model().sourceModel()
    else:
        return view.model()


def source_indexes(indexes, view):
    """ Map model indexes through a views QSortFilterProxyModel
    """
    model = view.model()
    if isinstance(model, QSortFilterProxyModel):
        return list(map(model.mapToSource, indexes))
    else:
        return indexes


class VariablesListItemModel(VariableListModel):
    """
    An Variable list item model specialized for Drag and Drop.
    """
    MIME_TYPE = "application/x-Orange-VariableListModelData"

    def __init__(self, *args, primitive=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.primitive = primitive

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid():
            flags |= Qt.ItemIsDragEnabled
        else:
            flags |= Qt.ItemIsDropEnabled
        return flags

    @staticmethod
    def supportedDropActions():  # pylint: disable=arguments-differ
        return Qt.MoveAction  # pragma: no cover

    @staticmethod
    def supportedDragActions():
        return Qt.MoveAction  # pragma: no cover

    def mimeTypes(self):
        return [self.MIME_TYPE]

    def mimeData(self, indexlist):
        """
        Reimplemented.

        For efficiency reasons only the variable instances are set on the
        mime data (under `'_items'` property)
        """
        items = [self[index.row()] for index in indexlist]
        mime = QMimeData()
        # the encoded 'data' is empty, variables are passed by properties
        mime.setData(self.MIME_TYPE, b'')
        mime.setProperty("_items", items)
        return mime

    def dropMimeData(self, mime, action, row, column, parent):
        """
        Reimplemented.
        """
        if action == Qt.IgnoreAction:
            return True
        if not mime.hasFormat(self.MIME_TYPE):
            return False
        variables = mime.property("_items")
        if variables is None:
            return False
        if row < 0:
            row = self.rowCount()

        if self.primitive and not all(var.is_primitive() for var in variables):
            variables = [var for var in variables if var.is_primitive()]
            self[row:row] = variables
            mime.setProperty("_moved", variables)
            return bool(variables)

        self[row:row] = variables
        mime.setProperty("_moved", True)
        return True


class SelectedVarsView(VariablesListItemView):
    """
    VariableListItemView that supports partially accepted drags.

    Upon finish, the mime data contains a list of variables accepted by the
    destination, and removes only those variables from the model.
    """
    def startDrag(self, supported_actions):
        indexes = self.selectedIndexes()
        if len(indexes) == 0:
            return
        data = self.model().mimeData(indexes)
        if not data:
            return
        drag = QDrag(self)
        drag.setMimeData(data)
        res = drag.exec(supported_actions, Qt.DropAction.MoveAction)

        moved = data.property("_moved")
        if moved is None:
            return

        if moved is True:
            # A quicker path if everything is moved.
            # When removing rows, private method QAbstractItemView::clearOrRemove
            # iterates over ranges and removes them, apparently assuming their
            # reverse order. I haven't found any guarantee for this order in
            # documentation (nor, actually, in the code that maintains their
            # order, so let's sort them.
            to_remove = sorted(
                ((index.top(), index.bottom() + 1)
                 for index in self.selectionModel().selection()),
                reverse=True)
        else:
            moved = set(moved)
            to_remove = reversed(list(slices(
                index.row() for index in self.selectionModel().selectedIndexes()
                if index.data(gui.TableVariable) in moved)))

        for start, end in to_remove:
            self.model().removeRows(start, end - start)

        self.dragDropActionDidComplete.emit(res)


class PrimitivesView(SelectedVarsView):
    """
    A SelectedVarsView that accepts drops events if it contains *any*
    primitive variables. This overrides the inherited behaviour that accepts
    the event only if *all* variables are primitive.
    """
    def acceptsDropEvent(self, event: QDropEvent) -> bool:
        if event.source() is not None and \
                event.source().window() is not self.window():
            return False  # pragma: nocover

        mime = event.mimeData()
        items = mime.property('_items')
        if items is None or not any(var.is_primitive() for var in items):
            return False

        event.accept()
        return True


# It is, what it is (and should be), pylint: disable=invalid-name
class SelectAttributesDomainContextHandler(DomainContextHandler):
    # Context handler's methods have variable arguments,
    # pylint: disable=arguments-differ,keyword-arg-before-vararg
    def encode_setting(self, context, setting, value):
        if setting.name == 'domain_role_hints':
            value = {(var.name, vartype(var)): role_i
                     for var, role_i in value.items()}
        return super().encode_setting(context, setting, value)

    def decode_setting(self, setting, value, domain=None, *_args):
        decoded = super().decode_setting(setting, value, domain)
        if setting.name == 'domain_role_hints':
            decoded = {domain[name]: role_i
                       for (name, _), role_i in decoded.items()}
        return decoded

    def match(self, context, domain, attrs, metas):
        if context.attributes == attrs and context.metas == metas:
            return self.PERFECT_MATCH

        if not "domain_role_hints" in context.values:
            return self.NO_MATCH

        all_vars = attrs.copy()
        all_vars.update(metas)
        value = context.values["domain_role_hints"][0]
        assigned = [desc for desc, (role, _) in value.items()
                    if role != "available"]
        if not assigned:
            return self.NO_MATCH
        return sum(all_vars.get(attr) == vtype for attr, vtype in assigned) \
               / len(assigned)

    def filter_value(self, setting, data, domain, attrs, metas):
        if setting.name != "domain_role_hints":
            super().filter_value(setting, data, domain, attrs, metas)
            return

        all_vars = attrs.copy()
        all_vars.update(metas)
        value = data["domain_role_hints"][0].items()
        data["domain_role_hints"] = {desc: role_i
                                     for desc, role_i in value
                                     if all_vars.get(desc[0]) == desc[1]}


class OWSelectAttributes(widget.OWWidget):
    # pylint: disable=too-many-instance-attributes
    name = "选择列 Select Columns"
    description = "从数据表中选择列,并将它们分配到 " \
                  "数据特征、类或元变量。"
    category = "变换"
    icon = "icons/SelectColumns.svg"
    priority = 100
    keywords = "选择列,过滤,属性,目标,变量"

    class Inputs:
        data = Input("数据", Table, default=True)
        features = Input("Features", AttributeList)

    class Outputs:
        data = Output("数据", Table)
        features = Output("Features", AttributeList, dynamic=False)

    want_main_area = False
    want_control_area = True

    settingsHandler = SelectAttributesDomainContextHandler(first_match=False)
    domain_role_hints = ContextSetting({})
    use_input_features = Setting(False)
    ignore_new_features = Setting(False)
    auto_commit = Setting(True)

    class Warning(widget.OWWidget.Warning):
        mismatching_domain = Msg("特征和数据域不匹配")
        multiple_targets = Msg("大多数小部件不支持多个目标")

    def __init__(self):
        super().__init__()
        self.data = None
        self.features = None

        # Schedule interface updates (enabled buttons) using a coalescing
        # single shot timer (complex interactions on selection and filtering
        # updates in the 'available_attrs_view')
        self.__interface_update_timer = QTimer(self, interval=0, singleShot=True)
        self.__interface_update_timer.timeout.connect(
            self.__update_interface_state)
        # If __update_var_counts were connected directly to textChanged of
        # view box's edit, it could be called before the related proxy is
        # updated
        self.__var_counts_update_timer = QTimer(self, interval=0, singleShot=True)
        self.__var_counts_update_timer.timeout.connect(
            self.update_var_counts)
        # The last view that has the selection for move operation's source
        self.__last_active_view = None  # type: Optional[QListView]

        def update_on_change(view):
            # Schedule interface state update on selection change in `view`
            self.__last_active_view = view
            self.__interface_update_timer.start()

        new_control_area = QWidget(self.controlArea)
        self.controlArea.layout().addWidget(new_control_area)
        self.controlArea = new_control_area

        # init grid
        self.view_boxes = []
        layout = QGridLayout()
        self.controlArea.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        name = "忽略"
        box = gui.vBox(self.controlArea, name,
                       addToLayout=False)

        self.available_attrs = VariablesListItemModel()
        filter_edit, self.available_attrs_view = variables_filter(
            parent=self, model=self.available_attrs,
            view_type=SelectedVarsView
        )
        box.layout().addWidget(filter_edit)
        self.view_boxes.append((name, box, self.available_attrs_view))
        filter_edit.textChanged.connect(self.__var_counts_update_timer.start)

        def dropcompleted(action):
            if action == Qt.MoveAction:
                self.commit.deferred()

        self.available_attrs_view.selectionModel().selectionChanged.connect(
            partial(update_on_change, self.available_attrs_view))
        self.available_attrs_view.dragDropActionDidComplete.connect(dropcompleted)

        box.layout().addWidget(self.available_attrs_view)
        layout.addWidget(box, 0, 0, 3, 1)

        # 3rd column
        name = "特征"
        box = gui.vBox(self.controlArea, name, addToLayout=False)
        self.used_attrs = VariablesListItemModel(primitive=True)
        filter_edit, self.used_attrs_view = variables_filter(
            parent=self, model=self.used_attrs,
            accepted_type=(Orange.data.DiscreteVariable,
                           Orange.data.ContinuousVariable),
            view_type=PrimitivesView)
        self.used_attrs.rowsInserted.connect(self.__used_attrs_changed)
        self.used_attrs.rowsRemoved.connect(self.__used_attrs_changed)
        self.used_attrs_view.selectionModel().selectionChanged.connect(
            partial(update_on_change, self.used_attrs_view))
        self.used_attrs_view.dragDropActionDidComplete.connect(dropcompleted)
        self.use_features_box = gui.auto_commit(
            self.controlArea, self, "use_input_features",
            "使用输入特征", "总是使用输入特征",
            box=False, commit=self.__use_features_clicked,
            callback=self.__use_features_changed, addToLayout=False
        )
        self.enable_use_features_box()
        box.layout().addWidget(self.use_features_box)
        box.layout().addWidget(filter_edit)
        box.layout().addWidget(self.used_attrs_view)
        layout.addWidget(box, 0, 2, 1, 1)
        self.view_boxes.append((name, box, self.used_attrs_view))
        filter_edit.textChanged.connect(self.__var_counts_update_timer.start)

        name = "目标"
        box = gui.vBox(self.controlArea, name, addToLayout=False)
        self.class_attrs = VariablesListItemModel(primitive=True)
        self.class_attrs_view = PrimitivesView(
            acceptedType=(Orange.data.DiscreteVariable,
                          Orange.data.ContinuousVariable),
        )
        self.class_attrs_view.setModel(self.class_attrs)
        self.class_attrs_view.selectionModel().selectionChanged.connect(
            partial(update_on_change, self.class_attrs_view))
        self.class_attrs_view.dragDropActionDidComplete.connect(dropcompleted)

        box.layout().addWidget(self.class_attrs_view)
        layout.addWidget(box, 1, 2, 1, 1)
        self.view_boxes.append((name, box, self.class_attrs_view))

        name = "元数据"
        box = gui.vBox(self.controlArea, name, addToLayout=False)
        self.meta_attrs = VariablesListItemModel()
        self.meta_attrs_view = SelectedVarsView(
            acceptedType=Orange.data.Variable)
        self.meta_attrs_view.setModel(self.meta_attrs)
        self.meta_attrs_view.selectionModel().selectionChanged.connect(
            partial(update_on_change, self.meta_attrs_view))
        self.meta_attrs_view.dragDropActionDidComplete.connect(dropcompleted)
        box.layout().addWidget(self.meta_attrs_view)
        layout.addWidget(box, 2, 2, 1, 1)
        self.view_boxes.append((name, box, self.meta_attrs_view))

        # 2nd column
        bbox = gui.vBox(self.controlArea, addToLayout=False, margin=0)
        self.move_attr_button = gui.button(
            bbox, self, ">",
            callback=partial(self.move_selected,
                             self.used_attrs_view, primitive=True)
        )
        layout.addWidget(bbox, 0, 1, 1, 1)

        bbox = gui.vBox(self.controlArea, addToLayout=False, margin=0)
        self.move_class_button = gui.button(
            bbox, self, ">",
            callback=partial(self.move_selected,
                             self.class_attrs_view, primitive=True)
        )
        layout.addWidget(bbox, 1, 1, 1, 1)

        bbox = gui.vBox(self.controlArea, addToLayout=False)
        self.move_meta_button = gui.button(
            bbox, self, ">",
            callback=partial(self.move_selected,
                             self.meta_attrs_view)
        )
        layout.addWidget(bbox, 2, 1, 1, 1)

        # footer
        gui.button(self.buttonsArea, self, "重置", callback=self.reset)

        bbox = gui.vBox(self.buttonsArea)
        gui.checkBox(
            widget=bbox,
            master=self,
            value="ignore_new_features",
            label="默认忽略新变量",
            tooltip="当小部件接收具有附加列的数据时 "
                    "如果勾选了 <i>默认忽略新变量</i>,它们将添加到可用属性列中 "
                    "<i>Ignore new variables by default</i> is checked."
        )

        gui.rubber(self.buttonsArea)
        gui.auto_send(self.buttonsArea, self, "auto_commit")

        layout.setRowStretch(0, 2)
        layout.setRowStretch(1, 0)
        layout.setRowStretch(2, 1)
        layout.setHorizontalSpacing(0)
        self.controlArea.setLayout(layout)

        self.output_data = None
        self.original_completer_items = []

        self.resize(600, 600)

    @property
    def features_from_data_attributes(self):
        if self.data is None or self.features is None:
            return []
        domain = self.data.domain
        return [domain[feature.name] for feature in self.features
                if feature.name in domain and domain[feature.name]
                in domain.attributes]

    def can_use_features(self):
        return bool(self.features_from_data_attributes) and \
               self.features_from_data_attributes != self.used_attrs[:]

    def __use_features_changed(self):  # Use input features check box
        # Needs a check since callback is invoked before object is created
        if not hasattr(self, "use_features_box"):
            return
        self.enable_used_attrs(not self.use_input_features)
        if self.use_input_features and self.can_use_features():
            self.use_features()
        if not self.use_input_features:
            self.enable_use_features_box()

    @gui.deferred
    def __use_features_clicked(self):  # Use input features button
        self.use_features()

    def __used_attrs_changed(self):
        self.enable_use_features_box()

    @Inputs.data
    def set_data(self, data=None):
        self.update_domain_role_hints()
        self.closeContext()
        self.domain_role_hints = {}

        self.data = data
        if data is None:
            self.used_attrs[:] = []
            self.class_attrs[:] = []
            self.meta_attrs[:] = []
            self.available_attrs[:] = []
            return

        self.openContext(data)
        all_vars = data.domain.variables + data.domain.metas

        def attrs_for_role(role):
            selected_attrs = [
                attr for attr in all_vars if domain_hints[attr][0] == role
            ]
            return sorted(selected_attrs, key=lambda attr: domain_hints[attr][1])

        domain_hints = self.restore_hints(data.domain)
        self.used_attrs[:] = attrs_for_role("attribute")
        self.class_attrs[:] = attrs_for_role("class")
        self.meta_attrs[:] = attrs_for_role("meta")
        self.available_attrs[:] = attrs_for_role("available")

        self.update_interface_state(self.class_attrs_view)

    def restore_hints(self, domain: Domain) -> Dict[Variable, Tuple[str, int]]:
        """
        Define hints for selected/unselected features.
        Rules:
        - if context available, restore new features based on checked/unchecked
          ignore_new_features, context hint should be took into account
        - in no context, restore features based on the domain (as selected)

        Parameters
        ----------
        domain
            Data domain

        Returns
        -------
        Dictionary with hints about order and model in which each feature
        should appear
        """
        domain_hints = {}
        if not self.ignore_new_features or len(self.domain_role_hints) == 0:
            # select_new_features selected or no context - restore based on domain
            domain_hints.update(
                self._hints_from_seq("attribute", domain.attributes)
            )
            domain_hints.update(self._hints_from_seq("meta", domain.metas))
            domain_hints.update(
                self._hints_from_seq("class", domain.class_vars)
            )
        else:
            # if context restored and ignore_new_features selected - restore
            # new features as available
            d = domain.attributes + domain.metas + domain.class_vars
            domain_hints.update(self._hints_from_seq("available", d))

        domain_hints.update(self.domain_role_hints)
        return domain_hints

    def update_domain_role_hints(self):
        """ Update the domain hints to be stored in the widgets settings.
        """
        hints = {}
        hints.update(self._hints_from_seq("available", self.available_attrs))
        hints.update(self._hints_from_seq("attribute", self.used_attrs))
        hints.update(self._hints_from_seq("class", self.class_attrs))
        hints.update(self._hints_from_seq("meta", self.meta_attrs))
        self.domain_role_hints = hints

    @staticmethod
    def _hints_from_seq(role, model):
        return [(attr, (role, i)) for i, attr in enumerate(model)]

    @Inputs.features
    def set_features(self, features):
        self.features = features

    def handleNewSignals(self):
        self.check_data()
        self.enable_used_attrs()
        self.enable_use_features_box()
        if self.use_input_features and self.features_from_data_attributes:
            self.enable_used_attrs(False)
            self.use_features()
        self.commit.now()

    def check_data(self):
        self.Warning.mismatching_domain.clear()
        if self.data is not None and self.features is not None and \
                not self.features_from_data_attributes:
            self.Warning.mismatching_domain()

    def enable_used_attrs(self, enable=True):
        self.move_attr_button.setEnabled(enable)
        self.used_attrs_view.setEnabled(enable)
        self.used_attrs_view.repaint()

    def enable_use_features_box(self):
        self.use_features_box.button.setEnabled(self.can_use_features())
        enable_checkbox = bool(self.features_from_data_attributes)
        self.use_features_box.setHidden(not enable_checkbox)
        self.use_features_box.repaint()

    def use_features(self):
        attributes = self.features_from_data_attributes
        available, used = self.available_attrs[:], self.used_attrs[:]
        self.available_attrs[:] = [attr for attr in used + available
                                   if attr not in attributes]
        self.used_attrs[:] = attributes
        self.commit.deferred()

    @staticmethod
    def selected_rows(view):
        """ Return the selected rows in the view.
        """
        rows = view.selectionModel().selectedRows()
        model = view.model()
        if isinstance(model, QSortFilterProxyModel):
            rows = [model.mapToSource(r) for r in rows]
        return [r.row() for r in rows]

    def move_rows(self, view: QListView, offset: int, roles=(Qt.EditRole,)):
        rows = [idx.row() for idx in view.selectionModel().selectedRows()]
        model = view.model()  # type: QAbstractItemModel
        rowcount = model.rowCount()
        newrows = [min(max(0, row + offset), rowcount - 1) for row in rows]

        def itemData(index):
            return {role: model.data(index, role) for role in roles}

        for row, newrow in sorted(zip(rows, newrows), reverse=offset > 0):
            d1 = itemData(model.index(row, 0))
            d2 = itemData(model.index(newrow, 0))
            model.setItemData(model.index(row, 0), d2)
            model.setItemData(model.index(newrow, 0), d1)

        selection = QItemSelection()
        for nrow in newrows:
            index = model.index(nrow, 0)
            selection.select(index, index)
        view.selectionModel().select(
            selection, QItemSelectionModel.ClearAndSelect)

        self.commit.deferred()

    def move_up(self, view: QListView):
        self.move_rows(view, -1)

    def move_down(self, view: QListView):
        self.move_rows(view, 1)

    def move_selected(self, view, *, primitive=False):
        if self.selected_rows(view):
            self.move_selected_from_to(view, self.available_attrs_view)
        elif self.selected_rows(self.available_attrs_view):
            self.move_selected_from_to(self.available_attrs_view, view,
                                       primitive)

    def move_selected_from_to(self, src, dst, primitive=False):
        rows = self.selected_rows(src)
        if primitive:
            model = src.model().sourceModel()
            rows = [row for row in rows if model[row].is_primitive()]
        self.move_from_to(src, dst, rows)

    def move_from_to(self, src, dst, rows):
        src_model = source_model(src)
        attrs = [src_model[r] for r in rows]

        for s1, s2 in reversed(list(slices(rows))):
            del src_model[s1:s2]

        dst_model = source_model(dst)

        dst_model.extend(attrs)

        self.commit.deferred()

    def __update_interface_state(self):
        last_view = self.__last_active_view
        if last_view is not None:
            self.update_interface_state(last_view)

    def update_var_counts(self):
        for name, box, view in self.view_boxes:
            model = view.model()
            source = source_model(view)  # may be the same as model
            nall = source.rowCount()
            nvars = view.model().rowCount()
            if source is not model and model.filter_string():
                box.setTitle(f"{name} ({nvars}/{nall})")
            elif nall:
                box.setTitle(f"{name} ({nvars})")
            else:
                box.setTitle(name)

    def update_interface_state(self, focus=None):
        self.update_var_counts()
        for *_, view in self.view_boxes:
            if view is not focus and not view.hasFocus() \
                    and view.selectionModel().hasSelection():
                view.selectionModel().clear()

        def selected_vars(view):
            model = source_model(view)
            return [model[i] for i in self.selected_rows(view)]

        available_selected = selected_vars(self.available_attrs_view)
        attrs_selected = selected_vars(self.used_attrs_view)
        class_selected = selected_vars(self.class_attrs_view)
        meta_selected = selected_vars(self.meta_attrs_view)

        available_types = set(map(type, available_selected))
        any_primitive = any(var.is_primitive()
                            for var in available_types)

        move_attr_enabled = \
            ((available_selected and any_primitive) or attrs_selected) and \
            self.used_attrs_view.isEnabled()

        self.move_attr_button.setEnabled(bool(move_attr_enabled))
        if move_attr_enabled:
            self.move_attr_button.setText(">" if available_selected else "<")

        move_class_enabled = bool(any_primitive and available_selected) or class_selected

        self.move_class_button.setEnabled(bool(move_class_enabled))
        if move_class_enabled:
            self.move_class_button.setText(">" if available_selected else "<")
        move_meta_enabled = available_selected or meta_selected

        self.move_meta_button.setEnabled(bool(move_meta_enabled))
        if move_meta_enabled:
            self.move_meta_button.setText(">" if available_selected else "<")

        # update class_vars height
        if self.class_attrs.rowCount() == 0:
            height = 22
        else:
            height = ((self.class_attrs.rowCount() or 1) *
                      self.class_attrs_view.sizeHintForRow(0)) + 2
        self.class_attrs_view.setFixedHeight(height)

        self.__last_active_view = None
        self.__interface_update_timer.stop()

    @gui.deferred
    def commit(self):
        self.update_domain_role_hints()
        self.Warning.multiple_targets.clear()
        if self.data is not None:
            attributes = list(self.used_attrs)
            class_var = list(self.class_attrs)
            metas = list(self.meta_attrs)

            domain = Orange.data.Domain(attributes, class_var, metas)
            newdata = self.data.transform(domain)
            self.output_data = newdata
            self.Outputs.data.send(newdata)
            self.Outputs.features.send(AttributeList(attributes))
            self.Warning.multiple_targets(shown=len(class_var) > 1)
        else:
            self.output_data = None
            self.Outputs.data.send(None)
            self.Outputs.features.send(None)

    def reset(self):
        self.enable_used_attrs()
        self.use_features_box.checkbox.setChecked(False)
        if self.data is not None:
            self.available_attrs[:] = []
            self.used_attrs[:] = self.data.domain.attributes
            self.class_attrs[:] = self.data.domain.class_vars
            self.meta_attrs[:] = self.data.domain.metas
            self.update_domain_role_hints()
            self.commit.now()

    def send_report(self):
        if not self.data or not self.output_data:
            return
        in_domain, out_domain = self.data.domain, self.output_data.domain
        self.report_domain("输入数据", self.data.domain)
        if (in_domain.attributes, in_domain.class_vars, in_domain.metas) == (
                out_domain.attributes, out_domain.class_vars, out_domain.metas):
            self.report_paragraph("输出数据", "无变化。")
        else:
            self.report_domain("输出数据", self.output_data.domain)
            diff = list(set(in_domain.variables + in_domain.metas) -
                        set(out_domain.variables + out_domain.metas))
            if diff:
                text = f'{len(diff)} ({", ".join(x.name for x in diff)})'
                self.report_items((("已移除", text),))


if __name__ == "__main__":  # pragma: no cover
    brown = Orange.data.Table("brown-selected")
    feats = AttributeList(brown.domain.attributes[:2])
    WidgetPreview(OWSelectAttributes).run(set_data=brown, set_features=feats)
