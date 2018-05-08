# The purpose of this script is to enable us to 
# run all the experiments by a single-line command 
# Arguments:
#   - Choice to pick Influence Function or Fusion Collison
#   - Choice to pick datasets (from ImageNet) 
#     by specifying the categories' names 
#   - Choice to pick num_train_per_class and num_test_per_class
#   - Choice to pick which experiments 
#   - Flexibility to pick the target test point 
#   - If test point chosen, flexibility to pick the target training point
#
# Outputs:
#   - Render the original selected training image, the poisoned image, and the target test point
#   - Give the model's initial prediction on the target test point
#   - Give the new model's final predicton on the target test point
#   - Give the tsne vis 

import os
import numpy as np
import IPython
import copy
from shutil import copyfile

import tensorflow as tf
from tensorflow.contrib.learn.python.learn.datasets import base

import sys
sys.dont_write_bytecode=True

PACKAGE_PARENT = '../'
SCRIPT_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser('__file__'))))
sys.path.append(os.path.normpath(os.path.join(SCRIPT_DIR, PACKAGE_PARENT)))

from influence.inceptionModel import BinaryInceptionModel
from influence.logisticRegressionWithLBFGS import LogisticRegressionWithLBFGS
from influence.binaryLogisticRegressionWithLBFGS import BinaryLogisticRegressionWithLBFGS
import influence.experiments
from influence.dataset import DataSet
# from influence.dataset_poisoning import iterative_attack, select_examples_to_attack, get_projection_to_box_around_orig_point, generate_inception_features
from influence.iter_attack import iterative_attack, select_examples_to_attack, get_projection_to_box_around_orig_point, generate_inception_features
from influence.Progress import *

from load_animals import *
from skimage import io
import matplotlib.pyplot as plt

## For now, pretend these are the arguments passed to the script 
#data_selected = ['Mushroom', 'Snail']
#num_train_ex_per_class = 500
#num_test_ex_per_class = 50
#use_IF = False # False implies FC
#target_test_idx = [15]
#target_labels = None
#num_to_perterb = 2
## --------End of arguments----------

def data_poisoning(data_selected, 
				   num_train_ex_per_class, num_test_ex_per_class,
				   use_IF,
				   target_test_idx,
				   num_to_perterb = 1,
				   target_labels = None):
	num_classes = len(data_selected)

	img_side = 299
	num_channels = 3

	initial_learning_rate = 0.001 
	keep_probs = None
	decay_epochs = [1000, 10000]
	weight_decay = 0.001
	max_lbfgs_iter = 1000
	batch_size = 50

	max_iter = 1000

	dataset_name = 'poisoning_%s_%s' % (num_train_ex_per_class, num_test_ex_per_class)
	valid_str = ''
	data_filename = os.path.join('../data/', 'dataset_%s_train-%s_test-%s%s.npz' % ('-'.join(data_selected), num_train_ex_per_class, num_test_ex_per_class, valid_str))
	if not os.path.exists(data_filename):
		extract_and_rename_animals()
	data_sets = load_animals(
					num_train_ex_per_class=num_train_ex_per_class, 
					num_test_ex_per_class=num_test_ex_per_class,
					classes=data_selected)

	if target_labels:
		assert len(target_labels) == len(target_test_idx)
		for label, test_idx in zip(target_test_idx, target_labels):
			assert data_sets.test.labels[test_idx] != label

	if not use_IF:
		assert len(target_test_idx) == 1

	# dataset_name = 'dogfish_%s_%s' % (num_train_ex_per_class, num_test_ex_per_class)
	# # extract_and_rename_animals()
	# data_sets = load_animals(
	#     num_train_ex_per_class=num_train_ex_per_class, 
	#     num_test_ex_per_class=num_test_ex_per_class,
	#     classes=data_selected)

	full_graph = tf.Graph()
	top_graph = tf.Graph()
	
	print('*** Full:')
	with full_graph.as_default():
		full_model_name = '%s_inception_wd-%s' % (dataset_name, weight_decay)
		full_model = BinaryInceptionModel(
			img_side=img_side,
			num_channels=num_channels,
			weight_decay=weight_decay,
			num_classes=num_classes, 
			batch_size=batch_size,
			data_sets=data_sets,
			initial_learning_rate=initial_learning_rate,
			keep_probs=keep_probs,
			decay_epochs=decay_epochs,
			mini_batch=True,
			train_dir='output',
			log_dir='log',
			model_name=full_model_name)

	if use_IF:
		with full_graph.as_default():
			for data_set, label in [
				(data_sets.train, 'train'),
				(data_sets.test, 'test')]:

				inception_features_path = 'output/%s_inception_features_new_%s.npz' % (dataset_name, label)
				if not os.path.exists(inception_features_path):

					print('Inception features do not exist. Generating %s...' % label)
					data_set.reset_batch()

					num_examples = data_set.num_examples
		#             assert num_examples % batch_size == 0

					inception_features_val = generate_inception_features(
						full_model, 
						data_set.x, 
						data_set.labels, 
						batch_size=batch_size)

					np.savez(
						inception_features_path, 
						inception_features_val=inception_features_val,
						labels=data_set.labels)
		train_f = np.load('output/%s_inception_features_new_train.npz' % dataset_name)
		inception_X_train = DataSet(train_f['inception_features_val'], train_f['labels'])
		test_f = np.load('output/%s_inception_features_new_test.npz' % dataset_name)
		inception_X_test = DataSet(test_f['inception_features_val'], test_f['labels'])
		validation = None
		inception_data_sets = base.Datasets(train=inception_X_train, validation=validation, test=inception_X_test)

		print('*** Top:')
		with top_graph.as_default():
			top_model_name = '%s_inception_onlytop_wd-%s' % (dataset_name, weight_decay)
			input_dim = 2048
			if num_classes == 2:
				LogReg = BinaryLogisticRegressionWithLBFGS
			else:
				LogReg = LogisticRegressionWithLBFGS
			top_model = LogReg(
				input_dim=input_dim,
				weight_decay=weight_decay,
				max_lbfgs_iter=max_lbfgs_iter,
				num_classes=num_classes, 
				batch_size=batch_size,
				data_sets=inception_data_sets,
				initial_learning_rate=initial_learning_rate,
				keep_probs=keep_probs,
				decay_epochs=decay_epochs,
				mini_batch=False,
				train_dir='output',
				log_dir='log',
				model_name=top_model_name)
			weights = top_model.retrain_and_get_weights(inception_X_train.x, inception_X_train.labels)
			orig_weight_path = 'output/inception_weights_%s.npy' % top_model_name
			np.save(orig_weight_path, weights)

		with full_graph.as_default():
			full_model.load_weights_from_disk(orig_weight_path, do_save=False, do_check=True)
	else:
		top_model = None
		top_graph = None 
		with full_graph.as_default():
			full_model.retrain_and_get_weights(data_sets.train.x, data_sets.train.labels)

	### Create poisoned dataset
	print('Creating poisoned dataset...')

	step_size = 0.02
	print('step_size is', step_size)

	num_train = len(data_sets.train.labels)
	num_test = len(data_sets.test.labels)
	max_num_to_poison = 10


	print('****** Attacking test_idx %s ******' % target_test_idx)
	test_description = target_test_idx

	# If this has already been successfully attacked, skip
	filenames = [filename for filename in os.listdir('./output') if (
		(('%s_attack_testidx-%s_trainidx-' % (full_model.model_name, test_description)) in filename) and        
		(filename.endswith('stepsize-%s_proj_final.npz' % step_size)))]
		# and (('stepsize-%s_proj_final.npz' % step_size) in filename))] # Check all step sizes        

	if use_IF:
		# Use top model to quickly generate inverse HVP
		with top_graph.as_default():
			get_hvp(
				top_model,
				inception_X_test, inception_X_train,
				test_description=test_description,
				test_idx = target_test_idx,
				force_refresh=True)
		copyfile(
			'output/%s-test-%s.npz' % (top_model_name, test_description),
			'output/%s-test-%s.npz' % (full_model_name, test_description))

		# Use full model to select indices to poison
		with full_graph.as_default():
			grad_influence_wrt_input_val_subset = get_grad_of_influence_wrt_input(full_model, 
														target_test_idx, data_sets.test, 
														np.arange(num_train), data_sets.train, 
														test_description,
														force_refresh=False)
			# save into file for caching 
			print("finished calculating grad_wrt_input_val")
			pred_diff = np.sum(np.abs(grad_influence_wrt_input_val_subset), axis = 1)
			index_to_poison = np.argsort(pred_diff)[-1:-num_to_perterb-1:-1]
	else:
		if target_labels is None:
			index_to_poison = np.random.choice(list(np.where(data_sets.train.labels != data_sets.test.labels[target_test_idx[0]])[0]), num_to_perterb)
		else:
			index_to_poison = np.random.choice(list(np.where(data_sets.train.labels == target_labels[0])[0]), num_to_perterb)
	print("all_indices_to_poison: ", index_to_poison)

	if use_IF:
		orig_X_train_inception_features_subset = np.copy(inception_X_train.x[index_to_poison, :])
		orig_X_train_subset = np.copy(data_sets.train.x[index_to_poison, :])
		project_fn = get_projection_to_box_around_orig_point(orig_X_train_subset, box_radius_in_pixels=0.5)
	else:
		project_fn = None
	beta = None
	if use_IF:
		attack_fn = iterative_attack
	else:
		beta = 2048.**2/(img_side*img_side*num_channels)**2*.25
		attack_fn = baseline_iterative_attack

	poisoned_image = attack_fn(top_model, full_model, top_graph, full_graph, project_fn, 
							  target_test_idx, 
							  test_description, 
							  data_sets.train, data_sets.test, dataset_name,
							  indices_to_poison=index_to_poison,
							  num_iter=200,
							  step_size=step_size,
							  save_iter=100,
							  early_stop=0.5,
							  beta = beta,
							  target_labels = target_labels)
	return poisoned_image
