"""
Classes for the model experiments. This is the overarching class that takes as an
input the name of the model, a dataset, a list of metrics to score the model by, and
any parameters required by said metrics.

Model inference here is done by pipline.
"""

import json
import os
import warnings
from datetime import datetime
from time import time
from typing import Tuple

import datasets
import torch
import wandb
from numpy.typing import ArrayLike
from transformers.modeling_utils import PreTrainedModel

from locomoset.datasets.load import load_dataset
from locomoset.datasets.preprocess import create_data_splits, drop_images
from locomoset.metrics.classes import Metric, MetricConfig
from locomoset.metrics.library import METRICS
from locomoset.models.features import get_features
from locomoset.models.load import get_model_without_head, get_processor


class ModelMetricsExperiment:
    """Model experiment class. Runs method metric.fit_metric() for each metric stated,
    which takes arguments: (model_input, dataset_input).
    """

    def __init__(self, config: MetricConfig) -> None:
        """Initialise model experiment class.

        Args:
            config: Dictionary containing the following:
                - model_name: name of model to be computed (str)
                - dataset_name: name of dataset to be scored by (str)
                - dataset_args: Dataset selection/filtering parameters, see the
                    docstring of the base Config class.
                - n_samples: number of samples for a metric experiment (int)
                - random_state: random seed for variation of experiments (int)
                - metrics: list of metrics to score (list(str))
                - (Optional) metric_kwargs: dictionary of entries
                    {metric_name: **metric_kwargs} containing parameters for each metric
                - (Optional) save_dir: Directory to save results, "results" if not set.
                - (Optional) device: which device to use for inference
        """
        # Parse model/seed config
        self.model_name = config.model_name
        self.random_state = config.random_state

        # Initialise metrics
        metric_kwargs_dict = config.metric_kwargs
        self.metrics = {
            metric: METRICS[metric](
                random_state=self.random_state, **metric_kwargs_dict.get(metric, {})
            )
            for metric in config.metrics
        }
        self.inference_types = list(
            set(metric.inference_type for metric in self.metrics.values())
        )

        # Caches
        if config.caches is not None:
            self.dataset_cache = config.caches["datasets"]
            self.model_cache = config.caches["models"]

        # Set up device
        self.device = config.device
        if self.device == "cuda":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Load/generate dataset
        print("Generating data sample...")
        self.dataset_name = config.dataset_name
        self.dataset = load_dataset(
            self.dataset_name,
            image_field=config.dataset_args["image_field"],
            label_field=config.dataset_args["label_field"],
            cache_dir=self.dataset_cache,
            keep_labels=config.dataset_args["keep_labels"],
        )

        # Prepare splits
        self.dataset = create_data_splits(
            self.dataset,
            train_split=config.dataset_args["train_split"],
            val_split=config.dataset_args["val_split"],
            test_split=config.dataset_args["test_split"],
            random_state=config.random_state,
            val_size=config.dataset_args["val_size"],
            test_size=config.dataset_args["test_size"],
        )

        # Grab train split
        self.dataset = self.dataset[config.dataset_args["train_split"]]

        # Take subset to create whole train dataset
        self.n_samples = config.n_samples
        self.dataset = drop_images(
            self.dataset,
            keep_size=self.n_samples,
            seed=config.random_state,
        )

        # Further subset train dataset to create metrics dataset
        self.metrics_samples = config.metrics_samples
        try:
            self.dataset = drop_images(
                self.dataset,
                keep_size=self.metrics_samples,
                seed=config.random_state,
            )
        except ValueError as error:
            if str(error).startswith(
                "The least populated class in label column has only 1 member"
            ):
                warnings.warn(
                    "The train set has only one sample of some classes so can't be "
                    "further subsetted with stratification to create the metrics set. "
                    "A random split has been used instead."
                )
                self.dataset = drop_images(
                    self.dataset,
                    keep_size=self.metrics_samples,
                    seed=config.random_state,
                    stratify_by_column=None,
                )
            else:
                raise error

        self.labels = self.dataset["label"]

        # Initialise results dict
        self.results = config.to_dict()
        self.results["inference_times"] = {}
        self.results["metric_scores"] = {}

        self.save_dir = config.save_dir
        os.makedirs(self.save_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.save_path = f"{self.save_dir}/results_{date_str}.json"

    def features_inference(self) -> ArrayLike:
        """Perform inference for features based methods.

        Returns:
            Features generated by the model with its classification head removed on the
                test dataset.
        """
        model_fn = get_model_without_head(self.model_name, cache=self.model_cache)
        processor = get_processor(self.model_name, cache=self.model_cache)
        return get_features(self.dataset, processor, model_fn, device=self.device)

    def model_inference(self) -> PreTrainedModel:
        """Perform inference for model based methods (just load the model).

        Returns:
            Model with its classification head removed.
        """
        return get_model_without_head(self.model_name, cache=self.model_cache)

    def perform_inference(
        self, inference_type: str | None
    ) -> tuple[ArrayLike, float] | tuple[None, float]:
        """Perform inference to retrieve data necessary for metric score computation.

        Args:
            inference_type: type of inference required, one of the following:
                - 'features': The model_input passed to the metric is features generated
                    by the model on the test dataset
                - 'model': The model_input passed to the metric is the model itself
                    (with its classification head removed)
                - None: model_input is set to None.

        Returns:
            Generated inference data (or None if nothing to generate) and computation
            time.
        """
        inference_start = time()
        if inference_type == "features":
            return self.features_inference(), time() - inference_start
        elif inference_type == "model":
            return self.model_inference(), time() - inference_start
        elif inference_type is not None:
            raise NotImplementedError(
                f"Not implemented inference for type '{inference_type}'"
            )
        return None, time() - inference_start

    def compute_metric_score(
        self,
        metric: Metric,
        model_input: ArrayLike | PreTrainedModel | None,
        dataset_input: ArrayLike | None,
    ) -> tuple[float, float] | tuple[int, float]:
        """Compute the metric score for a given metric. Not every metric requires
        either, or both, of the model_input or dataset_input but these are always input
        for a consistent pipeline (even if the input is None) and dealt with within the
        the model classes.

        Args:
            metric: metric object
            model_input: model input, type depends on metric inference type
            dataset_input: dataset input, from dataset (labels)

        Returns:
            metric score, computational time
        """
        metric_start = time()
        return (
            metric.fit_metric(model_input=model_input, dataset_input=dataset_input),
            time() - metric_start,
        )

    def run_experiment(self) -> dict:
        """Run the experiment pipeline

        Returns:
            dictionary of results
        """
        print(f"Scoring metrics: {self.metrics}")
        print(f"with inference types requires: {self.inference_types}")
        for inference_type in self.inference_types:
            print(f"Computing metrics with inference type {inference_type}")
            print("Running inference")
            model_input, inference_time = self.perform_inference(inference_type)
            self.results["inference_times"][inference_type] = inference_time

            test_metrics = [
                metric_name
                for metric_name, metric_obj in self.metrics.items()
                if metric_obj.inference_type == inference_type
            ]
            for metric in test_metrics:
                print(f"Computing metric score for {metric}")
                self.results["metric_scores"][metric] = {}
                score, metric_time = self.compute_metric_score(
                    self.metrics[metric],
                    model_input,
                    self.labels,
                )
                self.results["metric_scores"][metric]["score"] = score
                self.results["metric_scores"][metric]["time"] = metric_time

    def save_results(self) -> None:
        """Save the experiment results to self.save_path."""
        with open(self.save_path, "w") as f:
            json.dump(self.results, f, default=float)
        print(f"Results saved to {self.save_path}")

    def log_wandb_results(self) -> None:
        """Log the results to weights and biases."""
        wandb.log(self.results)
        wandb.finish()


def run_config(config: MetricConfig):
    """Run comparative metric experiment for a given pair (model, dataset) for stated
    metrics. Results saved to file path of form results/results_YYYYMMDD-HHMMSS.json by
    default.

    Args:
        config: Loaded configuration dictionary including the following keys:
            - models: a list of HuggingFace model names to experiment with.
            - dataset_name: Name of HuggingFace dataset to use.
            - dataset_split: Dataset split to use.
            - n_samples: List of how many samples (images) to compute the metric with.
            - random_state: List of random seeds to compute the metric with (used for
                subsetting the data and dimensionality reduction).
            - metrics: Which metrics to experiment on.
            - metric_kwargs: dictionary of entries {metric_name: **metric_kwargs}
                        containing parameters for each metric.
            - (Optional) save_dir: Directory to save results, "results" if not set.
    """

    if config.use_wandb:
        config.init_wandb()

    if config.caches.get("preprocess_cache") == "tmp":
        datasets.disable_caching()

    model_experiment = ModelMetricsExperiment(config)
    model_experiment.run_experiment()

    if config.local_save:
        model_experiment.save_results()

    if config.use_wandb:
        print(config.wandb_args)
        model_experiment.log_wandb_results()
