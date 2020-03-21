import copy
import functools
import math
import operator

from .. import base


__all__ = ['SuccessiveHalvingClassifier', 'SuccessiveHalvingRegressor']


class SuccessiveHalving:

    def __init__(self, models, metric, budget, eta=2, verbose=False):

        # Check that the model and the metric are in accordance
        for model in models:
            if not metric.works_with(model):
                raise ValueError(f"{metric.__class__.__name__} metric can't be used to evaluate a " +
                                f'{model.__class__.__name__}')

        self.models = models
        self.metric = metric
        self.budget = budget
        self.eta = eta
        self.verbose = verbose

        self._n = len(models)
        self._metrics = [copy.deepcopy(metric) for _ in range(self._n)]
        self._s = self._n
        self._n_rungs = 0
        self._rankings = list(range(self._n))
        self._r = math.floor(budget / (self._s * math.ceil(math.log(self._n, eta))))
        self._budget_used = 0
        self._n_iterations = 0
        self._best_model_idx = 0

        if isinstance(model, base.Classifier) and not metric.requires_labels:
            self._pred_func = lambda model: model.predict_proba_one
        else:
            self._pred_func = lambda model: model.predict_one

    @property
    def best_model(self):
        """The current best model."""
        return self.models[self._best_model_idx]

    def fit_one(self, x, y):

        for i in self._rankings[:self._s]:
            model = self.models[i]
            metric = self._metrics[i]
            y_pred = self._pred_func(model)(x)
            metric.update(y_true=y, y_pred=y_pred)
            model.fit_one(x, y)

            # Check for a new best model
            if i != self._best_model_idx:
                op = operator.gt if self.metric.bigger_is_better else operator.lt
                if op(self._metrics[i].get(), self._metrics[self._best_model_idx].get()):
                    self._best_model_idx = i

        self._n_iterations += 1

        if self._s > 1 and self._n_iterations == self._r:

            self._n_rungs += 1
            self._budget_used += self._s * self._r

            # Update the rankings of the current models based on their respective metric values
            self._rankings[:self._s] = sorted(
                self._rankings[:self._s],
                key=lambda i: self._metrics[i].get(),
                reverse=self.metric.bigger_is_better
            )

            # Determine how many models to keep for the current rung
            cutoff = math.ceil(self._s / self.eta)

            if self.verbose:
                print('\t'.join((
                    f'[{self._n_rungs}]',
                    f'{self._s - cutoff} removed',
                    f'{cutoff} left',
                    f'{self._r} iterations',
                    f'budget used: {self._budget_used}',
                    f'budget left: {self.budget - self._budget_used}',
                    f'best {self._metrics[self._rankings[0]]}',
                )))

            # Determine where the next rung is located
            self._s = cutoff
            self._r = math.floor(self.budget / (self._s * math.ceil(math.log(self._n, self.eta))))

        return self


class SuccessiveHalvingRegressor(SuccessiveHalving, base.Regressor):
    """Successive halving algorithm for regression.

    Successive halving is a method for performing model selection without having to train each
    model on all the dataset. At certain points in time (called "rungs"), the worst performing will
    be discarded and the best ones will keep competing between each other. The rung values are
    designed so that at most ``budget`` model updates will be performed in total.

    If you have ``k`` combinations of hyperparameters and that your dataset contains ``n``
    observations, then the maximal budget you can allocate is:

    .. math:: \\frac{2kn}{eta}

    It is recommended that you check this beforehand. This bound can't be checked by the function
    because the size of the dataset is not known. In fact it is potentially infinite, in which case
    the algorithm will terminate once all the budget has been spent.

    If you have a budget of ``B``, and that your dataset contains ``n`` observations, then the
    number of hyperparameter combinations that will spend all the budget and go through all the
    data is:

    .. math:: \\ceil(\\floor(\\frac{B}{(2n)}) \times eta)

    Parameters:
        model (models.Regressor)
        param_grid (dict): Parameter grid.
        X_y (generator): A stream of (features, target) tuples.
        metric (metrics.RegressionMetric): Metric used for comparing models with.
        budget (int): Total number of model updates you wish to allocate.
        eta (int): Rate of elimination. At every rung, ``math.ceil(k / eta)`` models are kept,
            where ``k`` is the number of models that have reached the rung. A higher ``eta`` value
            will focus on less models but will allocate more iterations to the best models.
        verbose (bool): Whether to display progress or not.

    Examples:

        ::

            >>> from creme import datasets
            >>> from creme import linear_model
            >>> from creme import metrics
            >>> from creme import preprocessing
            >>> from creme import model_selection
            >>> from creme import optim

            >>> model = (
            ...     preprocessing.StandardScaler() |
            ...     linear_model.LinearRegression(intercept_lr=.1)
            ... )

            >>> param_grid = model_selection.expand_param_grid({
            ...     'LinearRegression': {
            ...         'optimizer': [
            ...             (optim.SGD, {'lr': [0.1, 0.01, 0.005]}),
            ...             (optim.Adam, {'beta_1': [0.01, 0.001], 'lr': [0.1, 0.01, 0.001]}),
            ...             (optim.Adam, {'beta_1': [0.1], 'lr': [0.001]}),
            ...         ]
            ...     }
            ... })

            >>> models = [model._set_params(**params) for params in param_grid]

            >>> sh = model_selection.SuccessiveHalvingRegressor(
            ...     models=models,
            ...     metric=metrics.MAE(),
            ...     budget=2000,
            ...     eta=2,
            ...     verbose=True
            ... )

            >>> model_selection.progressive_val_score(
            ...     X_y=datasets.TrumpApproval(),
            ...     model=sh,
            ...     metric=metrics.MAE()
            ... )
            [1]	5 removed	5 left	50 iterations	budget used: 500	budget left: 1500	best MAE: 4.541564
            [2]	2 removed	3 left	100 iterations	budget used: 1000	budget left: 1000	best MAE: 2.453893
            [3]	1 removed	2 left	166 iterations	budget used: 1498	budget left: 502	best MAE: 1.579851
            [4]	1 removed	1 left	250 iterations	budget used: 1998	budget left: 2	    best MAE: 1.146581
            MAE: 0.472907

            >>> sh.best_model
            Pipeline (
              StandardScaler (
                with_mean=True
                with_std=True
              ),
              LinearRegression (
                optimizer=Adam (
                  lr=Constant (
                    learning_rate=0.1
                  )
                  beta_1=0.001
                  beta_2=0.999
                  eps=1e-08
                )
                loss=Squared ()
                l2=0.
                intercept=39.838695
                intercept_lr=Constant (
                  learning_rate=0.1
                )
                clip_gradient=1e+12
                initializer=Zeros ()
              )
            )

    References:
        1. `Jamieson, K. and Talwalkar, A., 2016, May. Non-stochastic best arm identification and hyperparameter optimization. In Artificial Intelligence and Statistics (pp. 240-248). <http://proceedings.mlr.press/v51/jamieson16.pdf>`_
        2. `Li, L., Jamieson, K., Rostamizadeh, A., Gonina, E., Hardt, M., Recht, B. and Talwalkar, A., 2018. Massively parallel hyperparameter tuning. arXiv preprint arXiv:1810.05934. <https://arxiv.org/pdf/1810.05934.pdf>`_
        3. `Li, L., Jamieson, K., DeSalvo, G., Rostamizadeh, A. and Talwalkar, A., 2017. Hyperband: A novel bandit-based approach to hyperparameter optimization. The Journal of Machine Learning Research, 18(1), pp.6765-6816. <https://arxiv.org/pdf/1603.06560.pdf>`_

    """

    def predict_one(self, x):
        return self.best_model.predict_one(x)


class SuccessiveHalvingClassifier(SuccessiveHalving, base.Classifier):
    """Successive halving algorithm for classification.

    Successive halving is a method for performing model selection without having to train each
    model on all the dataset. At certain points in time (called "rungs"), the worst performing will
    be discarded and the best ones will keep competing between each other. The rung values are
    designed so that at most ``budget`` model updates will be performed in total.

    If you have ``k`` combinations of hyperparameters and that your dataset contains ``n``
    observations, then the maximal budget you can allocate is:

    .. math:: \\frac{2kn}{eta}

    It is recommended that you check this beforehand. This bound can't be checked by the function
    because the size of the dataset is not known. In fact it is potentially infinite, in which case
    the algorithm will terminate once all the budget has been spent.

    If you have a budget of ``B``, and that your dataset contains ``n`` observations, then the
    number of hyperparameter combinations that will spend all the budget and go through all the
    data is:

    .. math:: \\ceil(\\floor(\\frac{B}{(2n)}) \times eta)

    Parameters:
        model (models.Classifier)
        param_grid (dict): Parameter grid.
        X_y (generator): A stream of (features, target) tuples.
        metric (metrics.ClassificationMetric): Metric used for comparing models with.
        budget (int): Total number of model updates you wish to allocate.
        eta (int): Rate of elimination. At every rung, ``math.ceil(k / eta)`` models are kept,
            where ``k`` is the number of models that have reached the rung. A higher ``eta`` value
            will focus on less models but will allocate more iterations to the best models.
        verbose (bool): Whether to display progress or not.

    Examples:

        ::

            >>> from creme import datasets
            >>> from creme import linear_model
            >>> from creme import metrics
            >>> from creme import preprocessing
            >>> from creme import model_selection
            >>> from creme import optim

            >>> model = (
            ...     preprocessing.StandardScaler() |
            ...     linear_model.LogisticRegression()
            ... )

            >>> param_grid = model_selection.expand_param_grid({
            ...     'LogisticRegression': {
            ...         'optimizer': [
            ...             (optim.SGD, {'lr': [0.1, 0.01, 0.005]}),
            ...             (optim.Adam, {'beta_1': [0.01, 0.001], 'lr': [0.1, 0.01, 0.001]}),
            ...             (optim.Adam, {'beta_1': [0.1], 'lr': [0.001]}),
            ...         ]
            ...     }
            ... })

            >>> models = [model._set_params(**params) for params in param_grid]

            >>> sh = model_selection.SuccessiveHalvingClassifier(
            ...     models=models,
            ...     metric=metrics.Accuracy(),
            ...     budget=2000,
            ...     eta=2,
            ...     verbose=True
            ... )

            >>> model_selection.progressive_val_score(
            ...     X_y=datasets.Phishing(),
            ...     model=sh,
            ...     metric=metrics.ROCAUC()
            ... )
            [1]	5 removed	5 left	50 iterations	budget used: 500	budget left: 1500	best Accuracy: 80.00%
            [2]	2 removed	3 left	100 iterations	budget used: 1000	budget left: 1000	best Accuracy: 84.00%
            [3]	1 removed	2 left	166 iterations	budget used: 1498	budget left: 502	best Accuracy: 86.75%
            [4]	1 removed	1 left	250 iterations	budget used: 1998	budget left: 2	    best Accuracy: 85.20%
            ROCAUC: 0.949693

            >>> sh.best_model
            Pipeline (
              StandardScaler (
                with_mean=True
                with_std=True
              ),
              LogisticRegression (
                optimizer=Adam (
                  lr=Constant (
                    learning_rate=0.01
                  )
                  beta_1=0.01
                  beta_2=0.999
                  eps=1e-08
                )
                loss=Log ()
                l2=0.
                intercept=-0.394786
                intercept_lr=Constant (
                  learning_rate=0.01
                )
                clip_gradient=1e+12
                initializer=Zeros ()
              )
            )

    References:
        1. `Jamieson, K. and Talwalkar, A., 2016, May. Non-stochastic best arm identification and hyperparameter optimization. In Artificial Intelligence and Statistics (pp. 240-248). <http://proceedings.mlr.press/v51/jamieson16.pdf>`_
        2. `Li, L., Jamieson, K., Rostamizadeh, A., Gonina, E., Hardt, M., Recht, B. and Talwalkar, A., 2018. Massively parallel hyperparameter tuning. arXiv preprint arXiv:1810.05934. <https://arxiv.org/pdf/1810.05934.pdf>`_
        3. `Li, L., Jamieson, K., DeSalvo, G., Rostamizadeh, A. and Talwalkar, A., 2017. Hyperband: A novel bandit-based approach to hyperparameter optimization. The Journal of Machine Learning Research, 18(1), pp.6765-6816. <https://arxiv.org/pdf/1603.06560.pdf>`_

    """

    def predict_proba_one(self, x):
        return self.best_model.predict_proba_one(x)
