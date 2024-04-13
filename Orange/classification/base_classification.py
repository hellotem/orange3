from Orange.base import Learner, Model, SklLearner, SklModel

__all__ = ["LearnerClassification", "ModelClassification",
           "SklModelClassification", "SklLearnerClassification"]


class LearnerClassification(Learner):

    def incompatibility_reason(self, domain):
        reason = None
        if len(domain.class_vars) > 1 and not self.supports_multiclass:
            reason = "目标变量太多。"
        elif not domain.has_discrete_class:
            reason = "期望分类类变量。"
        return reason


class ModelClassification(Model):
    def predict_proba(self, data):
        return self(data, ret=Model.Probs)


class SklModelClassification(SklModel, ModelClassification):
    pass


class SklLearnerClassification(SklLearner, LearnerClassification):
    __returns__ = SklModelClassification
