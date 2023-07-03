"""
This script downloads the Atari D4RL datasets, preprocesses, and saves them as pickle files.
"""

import gym
import numpy as np

import collections
import pickle

import d4rl_atari

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--mix_games', type=bool, default=True)
args = parser.parse_args()

if args.mix_games == False:
	# Loop over all available datasets
	for env_name in ['video-pinball', 'ms-pacman', 'enduro']:
	# for env_name in ['breakout']:
		# for dataset_type in ['mixed', 'medium', 'expert']:
		for dataset_type in ['expert']:
			name = f'{env_name}-{dataset_type}-v2'
			env = gym.make(name, stack=False) # stack = [True, False]
			env.reset()
			# get the D4RL dataset
			dataset = env.get_dataset()

			N = dataset['rewards'].shape[0]
			data_ = collections.defaultdict(list)

			use_timeouts = False
			if 'timeouts' in dataset:
				use_timeouts = True

			episode_step = 0
			paths = []

			# Loop over all samples in the dataset
			for i in range(N//2):
				# done_bool determines whether the episode is done
				done_bool = bool(dataset['terminals'][i])
				if use_timeouts:
					# final_timestep determines whether the episode is done due to timeout
					final_timestep = dataset['timeouts'][i]
				else:
					final_timestep = (episode_step == 4096)
				
				# Construct the data for the current episode
				for k in ['observations', 'next_observations', 'actions', 'rewards', 'terminals']:
					if k == 'next_observations':
						try:
							data_[k].append(dataset['observations'][i+1])
						except IndexError:
							data_[k].append(dataset['observations'][i])
					else:
						data_[k].append(dataset[k][i])

				# If the episode is done, add the episode data to the list of episodes
				if done_bool or final_timestep:
					episode_step = 0
					episode_data = {}
					for k in data_:
						episode_data[k] = np.array(data_[k])
					paths.append(episode_data)
					data_ = collections.defaultdict(list)
				episode_step += 1

			returns = np.array([np.sum(p['rewards']) for p in paths])
			num_samples = np.sum([p['rewards'].shape[0] for p in paths])
			print(f'Number of samples collected: {num_samples}')
			print(f'Trajectory returns: mean = {np.mean(returns)}, std = {np.std(returns)}, max = {np.max(returns)}, min = {np.min(returns)}')

			with open(f'{name}-stacked.pkl', 'wb') as f:
				pickle.dump(paths, f)
else:
	paths = []

	# Loop over all available datasets
	for env_name in ['air-raid', 'space-invaders', 'pong', 'qbert']:
		dataset_type = 'mixed'
		name = f'{env_name}-{dataset_type}-v2'
		env = gym.make(name, stack=False) # stack = [True, False]
		env.reset()
		# get the D4RL dataset
		dataset = env.get_dataset()

		N = dataset['rewards'].shape[0]
		data_ = collections.defaultdict(list)

		use_timeouts = False
		if 'timeouts' in dataset:
			use_timeouts = True

		episode_step = 0
		sum_reward = 0

		# Loop over all samples in the dataset
		for i in range(N//2):
			# done_bool determines whether the episode is done
			done_bool = bool(dataset['terminals'][i])
			if use_timeouts:
				# final_timestep determines whether the episode is done due to timeout
				final_timestep = dataset['timeouts'][i]
			else:
				final_timestep = (episode_step == 4096)
			
			# Construct the data for the current episode
			for k in ['observations', 'next_observations', 'actions', 'rewards', 'terminals']:
				if k == 'next_observations':
					try:
						data_[k].append(dataset['observations'][i+1])
					except IndexError:
						data_[k].append(dataset['observations'][i])
				elif k == 'rewards':
					sum_reward += dataset[k][i]
					data_[k].append(dataset[k][i])
				else:
					data_[k].append(dataset[k][i])

			# If the episode is done, add the episode data to the list of episodes
			if done_bool or final_timestep:
				episode_step = 0
				episode_data = {}
				for k in data_:
					# normalize rewards
					if k == 'rewards':
						episode_data[k] = np.array(data_[k]) / sum_reward
					else:
						episode_data[k] = np.array(data_[k])
				paths.append(episode_data)
				data_ = collections.defaultdict(list)
				sum_reward = 0
			episode_step += 1

		num_samples = np.sum([p['rewards'].shape[0] for p in paths])
		print('='*60)
		print(f'Number of samples collected: {num_samples}')

	with open(f'synthetic_data.pkl', 'wb') as f:
		pickle.dump(paths, f)