from concurrent.futures import Future, ThreadPoolExecutor
from typing import NamedTuple, Union, Optional, List

import numpy as np

from Orange.data import Domain, Table, Storage
from Orange.data.sql.table import SqlTable
from Orange.statistics import basic_stats
from Orange.widgets.utils import datacaching
from Orange.widgets.utils.localization import pl


# Table Summary
class _ArrayStat(NamedTuple):
    # Basic statistics for X/Y/metas arrays
    nans: int
    non_nans: int
    stats: np.ndarray


class DenseArray(_ArrayStat):
    pass


class SparseArray(_ArrayStat):
    pass


class SparseBoolArray(_ArrayStat):
    pass


#: Orange.data.Table summary
class Summary(NamedTuple):
    len: int
    domain: Domain
    X: Optional[_ArrayStat]
    Y: Optional[_ArrayStat]
    M: Optional[_ArrayStat]


#: Orange.data.sql.table.SqlTable summary
class ApproxSummary(NamedTuple):
    approx_len: int
    len: 'Future[int]'
    domain: Domain
    X: Optional[_ArrayStat]
    Y: Optional[_ArrayStat]
    M: Optional[_ArrayStat]


def _sql_table_len(table) -> 'Future[int]':
    exc = ThreadPoolExecutor()
    return exc.submit(table.__len__)


def table_summary(table: Table) -> Union[Summary, ApproxSummary]:
    if isinstance(table, SqlTable):
        approx_len = table.approx_len()
        len_future = datacaching.getCached(table, _sql_table_len, (table,))
        return ApproxSummary(approx_len, len_future, table.domain,
                             None, None, None)
                             # NotAvailable(), NotAvailable(), NotAvailable())
    else:
        domain = table.domain
        n_instances = len(table)
        bstats = datacaching.getCached(
            table, basic_stats.DomainBasicStats, (table, True)
        )

        dist = bstats.stats
        # pylint: disable=unbalanced-tuple-unpacking
        X_dist, Y_dist, M_dist = np.split(
            dist, np.cumsum([len(domain.attributes),
                             len(domain.class_vars)]))

        def parts(density, col_dist):
            nans = sum(dist.nans for dist in col_dist)
            non_nans = sum(dist.non_nans for dist in col_dist)
            if density == Storage.DENSE:
                return DenseArray(nans, non_nans, col_dist)
            elif density == Storage.SPARSE:
                return SparseArray(nans, non_nans, col_dist)
            elif density == Storage.SPARSE_BOOL:
                return SparseBoolArray(nans, non_nans, col_dist)
            elif density == Storage.MISSING:
                return None
            else:
                raise ValueError
        X_part = parts(table.X_density(), X_dist)
        Y_part = parts(table.Y_density(), Y_dist)
        M_part = parts(table.metas_density(), M_dist)
        return Summary(n_instances, domain, X_part, Y_part, M_part)


def format_summary(summary: Union[ApproxSummary, Summary]) -> List[str]:
    def format_part(part: Optional[_ArrayStat]) -> str:
        if isinstance(part, DenseArray):
            if not part.nans:
                return ""
            perc = 100 * part.nans / (part.nans + part.non_nans)
            return f" ({perc:.1f} % 缺失数据)"

        if isinstance(part, SparseArray):
            tag = "稀疏"
        elif isinstance(part, SparseBoolArray):
            tag = "标签"
        else:  # isinstance(part, NotAvailable)
            return ""
        dens = 100 * part.non_nans / (part.nans + part.non_nans)
        return f" ({tag}, 密度 {dens:.2f} %)"

    text = []
    if isinstance(summary, ApproxSummary):
        if summary.len.done():
            ninst = summary.len.result()
            text.append(f"{ninst} {pl(ninst, '实例')}")
        else:
            ninst = summary.approx_len
            text.append(f"~{ninst} {pl(ninst, '实例')}")
    elif isinstance(summary, Summary):
        ninst = summary.len
        text.append(f"{ninst} {pl(ninst, '实例')}")
        if sum(p.nans for p in [summary.X, summary.Y, summary.M]) == 0:
            text[-1] += " (无缺失数据)"

    nattrs = len(summary.domain.attributes)
    text.append(f"{nattrs} {pl(nattrs, '特征')}"
                + format_part(summary.X))

    if not summary.domain.class_vars:
        text.append("无目标变量。")
    else:
        nclasses = len(summary.domain.class_vars)
        if nclasses > 1:
            c_text = f"{nclasses} {pl(nclasses, '结果')}"
        elif summary.domain.has_continuous_class:
            c_text = "数值结果"
        else:
            nvalues = len(summary.domain.class_var.values)
            c_text = f"目标有 {nvalues} {pl(nvalues, '值')}"
        text.append(c_text + format_part(summary.Y))

    nmetas = len(summary.domain.metas)
    if nmetas:
        text.append(f"{nmetas} {pl(nmetas, '元属性')}"
                    + format_part(summary.M))
    else:
        text.append("无元属性。")
    return text
