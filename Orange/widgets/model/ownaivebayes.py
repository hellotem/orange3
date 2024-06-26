"""Naive Bayes Learner
"""

from Orange.data import Table
from Orange.classification.naive_bayes import NaiveBayesLearner
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview


class OWNaiveBayes(OWBaseLearner):
    name = "朴素贝叶斯 Naive Bayes"
    description = "一种基于" \
                  "贝叶斯定理并假设特征独立的快速简单概率分类器。"
    icon = "icons/NaiveBayes.svg"
    replaces = [
        "Orange.widgets.classify.ownaivebayes.OWNaiveBayes",
    ]
    priority = 70
    keywords = "naive bayes"

    LEARNER = NaiveBayesLearner


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWNaiveBayes).run(Table("iris"))
