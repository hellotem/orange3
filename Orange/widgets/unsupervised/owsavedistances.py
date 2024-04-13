from Orange.widgets.widget import Input, Msg
from Orange.misc import DistMatrix
from Orange.widgets.utils.save.owsavebase import OWSaveBase
from Orange.widgets.utils.widgetpreview import WidgetPreview


class OWSaveDistances(OWSaveBase):
    name = "保存距离矩阵 Save Distance Matrix"
    description = "将距离矩阵保存到输出文件"
    icon = "icons/SaveDistances.svg"
    keywords = "save distance matrix, distance matrix, save"

    filters = ["Excel 文件 (*.xlsx)", "距离文件 (*.dst)"]

    class Warning(OWSaveBase.Warning):
        table_not_saved = Msg("相关联的数据未保存")
        part_not_saved = Msg("与 {} 相关联的数据未保存")

    class Inputs:
        distances = Input("距离", DistMatrix)

    @Inputs.distances
    def set_distances(self, data):
        self.data = data
        self.on_new_input()

    def do_save(self):
        dist = self.data
        dist.save(self.filename)
        skip_row = not dist.has_row_labels() and dist.row_items is not None
        skip_col = not dist.has_col_labels() and dist.col_items is not None
        self.Warning.table_not_saved(shown=skip_row and skip_col)
        self.Warning.part_not_saved("列" if skip_col else "行",
                                    shown=skip_row != skip_col,)

    def send_report(self):
        self.report_items((
            ("输入", "无" if self.data is None else self._description()),
            ("文件名", self.filename or "未设置")))

    def _description(self):
        dist = self.data
        labels = " 和 ".join(
            filter(None, (dist.row_items is not None and "行",
                          dist.col_items is not None and "列")))
        if labels:
            labels = f"; {labels} 标签"
        return f"{len(dist)}维矩阵{labels}"


if __name__ == "__main__":
    from Orange.data import Table
    from Orange.distance import Euclidean
    WidgetPreview(OWSaveDistances).run(Euclidean(Table("iris")))
