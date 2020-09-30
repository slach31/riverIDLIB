from creme.tree._attribute_observer import NominalAttributeRegressionObserver
from creme.tree._attribute_observer import NumericAttributeRegressionObserver
from .base import ActiveLeaf
from .base import InactiveLeaf
from .base import LearningNode


class ActiveLeafRegressor(ActiveLeaf):
    @staticmethod
    def new_nominal_attribute_observer():
        return NominalAttributeRegressionObserver()

    @staticmethod
    def new_numeric_attribute_observer():
        return NumericAttributeRegressionObserver()

    def manage_memory(self, criterion, last_check_ratio, last_check_vr, last_check_e):
        """ Trigger Attribute Observers' memory management routines.

        Currently, only `NumericAttributeRegressionObserver` has support to this feature.

        Parameters
        ----------
            criterion
                Split criterion
            last_check_ratio
                The ratio between the second best candidate's merit and the merit of the best
                split candidate.
            last_check_vr
                The best candidate's split merit.
            last_check_e
                Hoeffding bound value calculated in the last split attempt.
        """
        for obs in self.attribute_observers.values():
            if isinstance(obs, NumericAttributeRegressionObserver):
                obs.remove_bad_splits(criterion=criterion, last_check_ratio=last_check_ratio,
                                      last_check_vr=last_check_vr, last_check_e=last_check_e,
                                      pre_split_dist=self.stats)


class LearningNodeMean(LearningNode):
    def __init__(self, initial_stats, depth):
        super().__init__(initial_stats, depth)

    def update_stats(self, y, sample_weight):
        try:
            self.stats[0] += sample_weight
            self.stats[1] += y * sample_weight
            self.stats[2] += y * y * sample_weight
        except KeyError:
            self.stats[0] = sample_weight
            self.stats[1] = y * sample_weight
            self.stats[2] = y * y * sample_weight

    def predict_one(self, X, *, tree=None):
        return self.stats[1] / self.stats[0] if self.stats else 0.

    @property
    def total_weight(self):
        """ Calculate the total weight seen by the node.

        Returns
        -------
        float
            Total weight seen.

        """
        return self.stats[0] if self.stats else 0.

    def calculate_promise(self) -> int:
        """ Estimate how likely a leaf node is going to be split.

        Uses the node's depth as a heuristic to estimate how likely the leaf is going to become
        a decision node. The deeper the node is in the tree, the more unlikely it is going to be
        split. To cope with the general tree memory management framework, takes the negative of
        the node's depth as return value. In this way, when sorting the tree leaves by their
        "promise value", the deepest nodes are going to be placed at the first positions as
        candidates to be deactivated.


        Returns
        -------
        int
            The smaller the value, the more unlikely the node is going to be split.

        """
        return -self.depth


class LearningNodeModel(LearningNodeMean):
    def __init__(self, initial_stats, depth, leaf_model):
        super().__init__(initial_stats, depth)
        self._leaf_model = leaf_model

    def learn_one(self, x, y, *, sample_weight=1.0, tree=None):
        super().learn_one(x, y, sample_weight=sample_weight, tree=tree)

        try:
            self._leaf_model.learn_one(x, y, sample_weight)
        except TypeError:  # Learning model does not support weights
            for _ in range(int(sample_weight)):
                self._leaf_model.learn_one(x, y)

    def predict_one(self, x, *, tree=None):
        return self._leaf_model.predict_one(x)


class LearningNodeAdaptive(LearningNodeModel):
    def __init__(self, initial_stats, depth, leaf_model):
        super().__init__(initial_stats, depth, leaf_model)
        self._fmse_mean = 0.
        self._fmse_model = 0.

    def learn_one(self, x, y, *, sample_weight=1.0, tree=None):
        pred_mean = self.stats[1] / self.stats[0] if self.stats else 0.
        pred_model = self._leaf_model.predict_one(x)

        self._fmse_mean = tree.model_selector_decay * self._fmse_mean + (y - pred_mean) ** 2
        self._fmse_model = tree.model_selector_decay * self._fmse_model + (y - pred_model) ** 2

        super().learn_one(x, y, sample_weight=sample_weight, tree=tree)

    def predict_one(self, x, *, tree=None):
        if self._fmse_mean < self._fmse_model:  # Act as a regression tree
            return self.stats[1] / self.stats[0] if self.stats else 0.
        else:  # Act as a model tree
            return super().predict_one(x)


class ActiveLearningNodeMean(LearningNodeMean, ActiveLeafRegressor):
    """ Learning Node for regression tasks that always use the average target
    value as response.

    Parameters
    ----------
    initial_stats
        In regression tasks this dictionary carries the sufficient to perform
        online variance calculation. They refer to the number of observations
        (key '0'), the sum of the target values (key '1'), and the sum of the
        squared target values (key '2').
    depth
        The depth of the node.
    """
    def __init__(self, initial_stats, depth):
        super().__init__(initial_stats, depth)


class InactiveLearningNodeMean(LearningNodeMean, InactiveLeaf):
    """ Inactive Learning Node for regression tasks that always use
    the average target value as response.

    Parameters
    ----------
    initial_stats
        In regression tasks this dictionary carries the sufficient to perform
        online variance calculation. They refer to the number of observations
        (key '0'), the sum of the target values (key '1'), and the sum of the
        squared target values (key '2').
    depth
        The depth of the node.
    """
    def __init__(self, initial_stats, depth):
        super().__init__(initial_stats, depth)


class ActiveLearningNodeModel(LearningNodeModel, ActiveLeafRegressor):
    """ Learning Node for regression tasks that always use a learning model to provide
    responses.

    Parameters
    ----------
    initial_stats
        In regression tasks this dictionary carries the sufficient statistics
        to perform online variance calculation. They refer to the number of
        observations (key '0'), the sum of the target values (key '1'), and
        the sum of the squared target values (key '2').
    depth
        The depth of the node.
    leaf_model
        A river.base.Regressor instance used to learn from instances and provide
        responses.
    """
    def __init__(self, initial_stats, depth, leaf_model):
        super().__init__(initial_stats, depth, leaf_model)


class InactiveLearningNodeModel(LearningNodeModel, InactiveLeaf):
    """ Inactive Learning Node for regression tasks that always use a learning model to
    provide responses.

    Parameters
    ----------
    initial_stats
        In regression tasks this dictionary carries the sufficient statistics
        to perform online variance calculation. They refer to the number of
        observations (key '0'), the sum of the target values (key '1'), and
        the sum of the squared target values (key '2').
    depth
        The depth of the node.
    leaf_model
        A river.base.Regressor instance used to learn from instances and provide
        responses.
    """
    def __init__(self, initial_stats, depth, leaf_model):
        super().__init__(initial_stats, depth, leaf_model)


class ActiveLearningNodeAdaptive(LearningNodeAdaptive, ActiveLeafRegressor):
    """ Learning Node for regression tasks that dynamically selects between predictors and
    might behave as a regression tree node or a model tree node, depending on which predictor
    is the best one.

    Parameters
    ----------
    initial_stats
        In regression tasks this dictionary carries the sufficient statistics
        to perform online variance calculation. They refer to the number of
        observations (key '0'), the sum of the target values (key '1'), and
        the sum of the squared target values (key '2').
    depth
        The depth of the node.
    leaf_model
        A river.base.Regressor instance used to learn from instances and provide
        responses.
    """
    def __init__(self, initial_stats, depth, leaf_model):
        super().__init__(initial_stats, depth, leaf_model)


class InactiveLearningNodeAdaptive(LearningNodeAdaptive, InactiveLeaf):
    """ Inactive Learning Node for regression tasks that dynamically selects between predictors
     might behave as a regression tree node or a model tree node, depending on which predictor
    is the best one.

    Parameters
    ----------
    initial_stats
        In regression tasks this dictionary carries the sufficient statistics
        to perform online variance calculation. They refer to the number of
        observations (key '0'), the sum of the target values (key '1'), and
        the sum of the squared target values (key '2').
    depth
        The depth of the node.
    leaf_model
        A river.base.Regressor instance used to learn from instances and provide
        responses.
    """
    def __init__(self, initial_stats, depth, leaf_model):
        super().__init__(initial_stats, depth, leaf_model)
