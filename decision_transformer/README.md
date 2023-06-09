# Decision Transformer

Paper: [Decision Transformer](https://arxiv.org/pdf/2106.01345.pdf), Official Code: [Code](https://github.com/kzl/decision-transformer)

### Conducted Experiments 

1. **Input data test**: Use data with 1 frame per step, and data with 4 frames per step. The code is stored in the folders `stack_states` and `no_stack_states`.

- General Info: The data with no stack weighs ~13GB, while the data with stacked frames weighs ~51GB, both contains 1M steps.
- Setup: The target return is set to 90 for both models in evaluation phase. The context length is 30 past steps, and both models have 1.9M parameters.
- Result: There is a small difference in the performance between the models trained on the two dataset. The non stacked model achieves on average 83 points over 10 episodes, while the stacked one gets 132 points on average over 10 episodes with the same seed.

2. **Out-of-distribution test**: The model is trained on multiple environments and tested on a new unseen environment. The code is stored in the folder `distribution_shift`.

- Data: The data is collected with 500,000 steps from 4 games `'air-raid', 'space-invaders', 'pong', 'qbert'`. In total, the dataset contains 2M steps and weighs ~26GB. The model is then evaluated on the `StarGunner` environment for the out-of-distribution test.
- Result: The agent successfully generalized to act intelligently in multiple environments that it has seen during training. However, it failed when we evaluate it in the unseen Star Gunner game. One of the main cause might be that the nature of the game Star Gunner is different from the games used to train the model. Star Gunner is a horizontal bullet tracking, while Pong is ball tracking, Qbert is position tracking, and Space Invaders and Air Raid are vertical bullet tracking. Therefore, the agent fails to understand when to shoot.

3. **Minimal version**: a minimal and easy to understand version of the decision transformer is reimplemented with comparable performance to the original model. A new and simple training procedure is also used to train both models in our experiments. The model is stored in the folder `minimal_model`.

- Changes we made compared to the original model:
    - The time embedding is simply a embedding lookup table instead of positional and global positional embeddings.
    - We focus only on the reward-conditioned case, and always padding the input instead of considering the case `actions = None`. 
    - The first action in our model is random, and the next few actions are predicted on the zero padded inputs. Since the Atari environment is sparse (in terms of rewards), that does not affect our model's performance.
    - We utilize a much simpler training procedure.
