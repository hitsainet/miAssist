---
title: Glossary
---

# Glossary

The words miAssist explains. Your assistant shows the same entries with `miassist_glossary`, and
every result links the words it uses.

## activate

Switching a cluster on in the inference server so it steers every reply; the operator does it.

Also called: activation, active.

See also: cluster.

## approval

A request an app holds until its operator says yes or no. You cannot approve it; the operator decides in the app.

Also called: approvals, pending approval.

See also: guidance level.

## armed

A detector the serving app runs on every chat, recording a verdict each time.

Also called: arm, arming.

See also: detector, parity.

## AUROC

A score from 0.5 (guessing) to 1.0 (perfect) for how well a probe tells the two kinds of text apart.

What good looks like: 0.9 or above on text the probe never saw.

Also called: area under the curve.

See also: probe, held-out.

## behaviour key

A short name, like refund-request, that ties a behaviour's data, runs and detectors together.

Also called: key, behavior key.

See also: detector.

## calibration bar

The score above which a probe says yes, chosen so it rarely raises a false alarm.

Also called: threshold, bar.

See also: false alarm.

## catch rate

The share of real positives the detector flags at its bar.

Also called: recall.

See also: shipped bar.

## check outcome

How a publish check ended: green passed; note is for your information; amber blocks a public publish only; refused blocks every publish.

Also called: green, note, amber, refused.

See also: publish check.

## checkpoint

A saved copy of model weights at one point in a training run.

Also called: checkpoints.

## circuit

A small set of model parts that work together to produce one behaviour.

Also called: circuits.

See also: feature, rung.

## cluster

A group of features steered together as one dial.

Also called: clusters, feature cluster.

See also: steering.

## dataset

A named collection whose numbered versions are built from sources by a recipe.

Also called: datasets.

See also: dataset version, source.

## dataset version

A frozen, numbered copy of a dataset that does not change after it is built.

Also called: version, versions.

## detector

Something that watches a model's activity and flags one kind of behaviour.

Also called: detectors.

See also: probe.

## dial

How much of a saved cluster is applied, from 0 (off) to 1 (the saved strengths).

Also called: intensity dial.

See also: cluster.

## duplicate

A row that is exactly the same as another row.

Also called: duplicates, exact duplicate.

See also: near-duplicate.

## everyday text

Ordinary messages that should not set the detector off; they measure false alarms.

Also called: everyday set.

See also: false alarm.

## evidence ladder

The steps of proof a result climbs, from a first guess to a tested claim.

Also called: ladder.

See also: rung.

## false alarm

When a detector says yes about text that is fine.

Also called: false alarms, false positive.

## feature

One direction inside a model that lights up for a recognisable idea.

Also called: features, SAE feature.

See also: SAE.

## fluent

A reply that still reads as language; one with fewer than 4 distinct words in 10 counts as fallen apart.

Also called: fluency, fallen apart.

See also: type-token ratio.

## GPU

The fast processor(s) that run models. Work that uses the GPU(s) available always waits for the app's operator.

Also called: GPUs, graphics card.

## guidance level

Beginner shows a short explanation with each result; expert leaves it out. Nothing else changes.

Also called: level, beginner, expert.

## held-out

Data kept aside and never used for training, so a test on it is fair.

Also called: held out, holdout.

## held-out split

A split kept apart for judging a model on rows it never learned from.

Also called: held-out splits.

See also: split, leakage.

## label run

A pass that labels each row of a dataset, by rules or by a judge model.

Also called: label runs, labelling.

## layer

One stage of the model's stack; a feature lives at one layer.

Also called: layers.

## leakage

The same or nearly the same rows in both training and held-out splits, which makes a model look better than it is.

Also called: data leakage.

See also: held-out split, near-duplicate.

## max activation

The strongest response a feature showed on the examples it was measured on; steering strengths are scaled from it.

Also called: highest activation.

See also: steering strength.

## near-duplicate

A row that is almost the same as another, differing only in small ways.

Also called: near-duplicates.

See also: duplicate, leakage.

## nonsense text

Made-up, meaningless text; a good detector stays quiet on it.

Also called: nonsense set.

See also: false alarm.

## out-of-distribution

Text unlike the training text, used to check a probe still works away from home.

Also called: OOD, out of distribution.

See also: held-out.

## pack

A bundle of the parts a training run needs: the data, the settings and the model to start from.

Also called: packs.

## parity

A check that the serving app scores text the same way the training app did.

Also called: parity check.

See also: armed.

## per-request trial

One short reply steered by a cluster for that request only, without switching it on for anyone else.

Also called: trial.

See also: activate.

## pooling rule

How a probe turns many per-word scores into one score for a whole text.

Also called: pooling.

See also: probe.

## positive meaning

What it means, in plain words, for the behaviour to be present in a message.

Also called: meaning.

See also: behaviour key.

## probe

A small classifier that reads a model's activity and scores one behaviour.

Also called: probes, probe monitor.

See also: detector, AUROC.

## publish check

One of the checks a dataset passes before it is published, numbered C-1 to C-9, each ending green, note, amber or refused.

Also called: publish checks, check run.

See also: check outcome.

## recipe

The saved steps that build a dataset version from its sources.

Also called: recipes.

See also: dataset version.

## recipe step

One step of a recipe, such as dropping duplicates or making splits; each has its own version and settings.

Also called: operator step.

See also: recipe.

## rung

One step on the evidence ladder; a higher rung means stronger proof.

Also called: rungs, rung 2.

See also: evidence ladder.

## SAE

A tool that splits a model's activity into many readable features.

Also called: sparse autoencoder, SAEs.

See also: feature.

## served model

The model the inference server has loaded and answers chat requests with.

Also called: loaded model, model.

## shipped bar

The score above which the detector says yes, set from ordinary messages.

Also called: bar, threshold.

See also: calibration bar.

## shortcut

A column that alone predicts the label, so a model could learn that column instead of the content.

Also called: shortcuts, shortcut audit.

See also: publish check.

## source

Data brought into the dataset app as it is, from the Hub or an upload, before any recipe runs.

Also called: sources, data source.

See also: dataset.

## split

A named part of a dataset, such as train, validation or test.

Also called: splits, train split, test split.

See also: held-out split.

## steering

Nudging a model's behaviour by turning features up or down while it answers.

Also called: steer.

See also: steering strength, cluster.

## steering strength

How hard a steering nudge pushes; too much makes answers strange.

Also called: strength, intensity.

See also: steering.

## sweep

One run that answers the same prompt with a feature turned up to several strengths, to compare the replies.

Also called: steering sweep.

See also: steering strength.

## type-token ratio

Distinct words divided by all words in a reply; repetition drives it down.

Also called: TTR.

See also: fluent.

## view

A dataset read one way: which column is the text, which the label, and what each label means.

Also called: views, probe dataset.

## visibility

Who can see a published dataset: private means only your Hub account; public means anyone.

Also called: private, public.
