import gym
import torch
from torch.nn import functional as F
import numpy as np

from utils import set_seed, AtariEnv
from dt_model import DecisionTransformer, GPTConfig
from official_model import GPT, GPTConfig

set_seed(123)

def get_trajectory(trajectory, observation, action, reward, step):
    """ Collect observed trajectory from the environment.
    """

    trajectory['observations'].append(observation)
    trajectory['actions'].append(action)
    trajectory['rewards'].append(reward)
    trajectory['steps'].append(step)

    return trajectory

def get_returns(rewards, target_return = 200):
    """ Calculate the returns to go.
    """

    returns_to_go = np.zeros(len(rewards))
    for i in range(len(rewards)):
        for j in range(i):
            returns_to_go[i] += rewards[j]
        returns_to_go[i] = target_return - returns_to_go[i]
    return returns_to_go

def make_action(trajectory, model, context_len, device):
    """ Given a state, return an action sampled from the model.
    """

    if len(trajectory['observations']) == 0:
        action = np.random.randint(0, 3)
    else:
        state_dim = 84
        if len(trajectory['observations']) < context_len:
            context_len = len(trajectory['observations'])
            states = torch.tensor(np.array(trajectory['observations']), dtype=torch.float32).reshape(1, context_len, 4, state_dim, state_dim).to(device)  # the current state is given
            actions = torch.tensor(trajectory['actions'], dtype=torch.long).reshape(1, context_len-1, 1).to(device)   # the action to the current state needs to be predicted
            timesteps = torch.tensor(trajectory['steps'][0], dtype=torch.int64).reshape(1,1,1).to(device)
            rewards = get_returns(trajectory['rewards'])
            rtgs = torch.tensor(rewards).reshape(1, context_len, 1).to(device)
        else:
            trajectory['observations'] = trajectory['observations'][-context_len:]
            trajectory['actions'] = trajectory['actions'][-context_len+1:]
            trajectory['rewards'] = trajectory['rewards'][-context_len:]
            states = torch.tensor(np.array(trajectory['observations'][-context_len:]), dtype=torch.float32).reshape(1, context_len, 4, state_dim, state_dim).to(device)  # the current state is given
            actions = torch.tensor(trajectory['actions'][-context_len+1:], dtype=torch.long).reshape(1, context_len-1, 1).to(device)   # the action to the current state needs to be predicted
            timesteps = torch.tensor(trajectory['steps'][-context_len], dtype=torch.int64).reshape(1,1,1).to(device)
            rewards = get_returns(trajectory['rewards'])
            rtgs = torch.tensor(rewards[-context_len:]).reshape(1, context_len, 1).to(device)
            
        with torch.no_grad():
            logits, _ = model.forward(states = states,
                                    actions = actions,
                                    targets = None,
                                    rtgs = rtgs,
                                    timesteps = timesteps)
            probs = F.softmax(logits[:, -1, :], dim=-1)
            action = torch.multinomial(probs, num_samples=1)
    return action

def experiment(device):

    env = AtariEnv(game='Breakout', stack=True)
    print("Observation space:", env.observation_space)
    # env.reset()
        
    state_dim = env.observation_space.shape[1] # state dimension
    act_dim = env.action_space.n # action dimension

    # conf = GPTConfig(state_dim=state_dim,
    #                     act_dim=act_dim)
    # model = DecisionTransformer(state_dim=conf.state_dim,
    #                             act_dim=conf.act_dim,
    #                             n_blocks=conf.n_blocks,
    #                             h_dim=conf.embed_dim,
    #                             context_len=conf.context_len,
    #                             n_heads=conf.n_heads,
    #                             drop_p=conf.dropout_p).to(device)
    conf = GPTConfig(vocab_size=act_dim, n_layer=6, n_head=8, n_embd=128, model_type='reward_conditioned', max_timestep=10000)
    model = GPT(conf).to(device)
    # Load the trained weights
    # path_to_model = "dt_runs/dt_breakout-expert-v2_stacked_model_5.pt"
    path_to_model = "decision_transformer/dt_runs/dt_breakout-expert-v2_stacked_model_5.pt"
    if torch.cuda.is_available():
        print('Using GPU')
        model.load_state_dict(torch.load(path_to_model))
    else:
        model.load_state_dict(torch.load(path_to_model, map_location=torch.device('cpu')))
    model.eval()
    print("Loaded model from:", path_to_model)

    max_episodes = 10
    cum_reward = 0

    for i in range(max_episodes):
        env.reset()
        trajectory = {'observations': [], 'actions': [], 'rewards': [], 'steps': []}
        action = make_action(trajectory, model, 30, device)
        # print(type(action), action)
        observation, reward, terminated, info = env.step(action)
        observation = np.array(observation) / 255.
        trajectory['observations'].append(observation)
        trajectory['rewards'].append(reward)
        trajectory['steps'].append(0)

        step = 1
        sum_reward = 0
        epsilon = 0.05
        while True:
            if np.random.random() < epsilon:
                action = np.random.randint(0, 3)
            else:
                action = make_action(trajectory, model, 30, device)
            observation, reward, terminated, info = env.step(action)
            env.render()
            observation = np.array(observation) / 255.
            trajectory = get_trajectory(trajectory, observation, action, reward, step)
            step += 1
            sum_reward += reward

            if terminated or step >= 10000:
                print("=" * 60)
                print("Episode:", i, "- Reward:", sum_reward, "- Steps:", step)
                cum_reward += sum_reward
                break

    env.close()
    print("=" * 60)
    print("Cum reward:", cum_reward, "out of", max_episodes, "episodes")
    print("Average reward:", cum_reward/max_episodes)

if __name__ == '__main__':
    device = torch.cuda.current_device() if torch.cuda.is_available() else "cpu"
    print("Using device: ", device)

    experiment(device=device)