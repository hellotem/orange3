from Orange.base import Learner, Model, SklLearner, SklModel

__all__ = ["LearnerRegression", "ModelRegression",
           "SklModelRegression", "SklLearnerRegression"]


class LearnerRegression(Learner):

    def incompatibility_reason(self, domain):
        reason = None
        if len(domain.class_vars) > 1 and not self.supports_multiclass:
            reason = "目标变量太多。"
        elif not domain.has_continuous_class:
            reason = "需要数值型目标变量。"
        return reason


class ModelRegression(Model):
    pass


class SklModelRegression(SklModel, ModelRegression):
    pass


class SklLearnerRegression(SklLearner, LearnerRegression):
    __returns__ = SklModelRegression
