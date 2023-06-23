import math
import logging
import numpy as np

import torch
import torch.nn as nn
from torch.nn import functional as F

class GPTConfig:
    def __init__(self, state_dim=84, act_dim=4, context_len=30, n_blocks=12, embed_dim=768, n_heads=12, dropout_p=0.1):
        self.state_dim = state_dim          # state dim
        self.act_dim = act_dim              # action dim
        self.context_len = context_len      # context length
        self.n_blocks = n_blocks            # num of transformer blocks
        self.embed_dim = embed_dim          # embedding (hidden) dim of transformer
        self.n_heads = n_heads              # num of transformer heads
        self.dropout_p = dropout_p          # dropout probability

class MaskedCausalAttention(nn.Module):
    def __init__(self, h_dim, max_T, n_heads, drop_p):
        super().__init__()
        assert h_dim % n_heads == 0, 'hidden dimension must be divisible by number of heads'

        self.n_heads = n_heads
        self.h_dim = h_dim
        self.max_T = max_T # vocab_size

        self.c_attn = nn.Linear(h_dim, 3 * h_dim)

        self.c_proj = nn.Linear(h_dim, h_dim)

        self.attn_dropout = nn.Dropout(drop_p)
        self.resid_dropout = nn.Dropout(drop_p)

        ones = torch.ones((max_T, max_T))
        mask = torch.tril(ones).view(1, 1, max_T, max_T) # mask for masked attention

        # register buffer makes sure mask does not get updated during back-propagation
        self.register_buffer('mask',mask)

    def forward(self, x):
        B, T, C = x.shape # batch size, seq length, state + action vector dimension

        N, D = self.n_heads, C // self.n_heads # N = num heads, D = h_dim

        # rearrange q, k, v as (B, N, T, D)
        q, k ,v  = self.c_attn(x).split(self.h_dim, dim=2)
        q = q.view(B, T, N, D).transpose(1,2) # (B, T, N, D) -> (B, N, T, D)
        k = k.view(B, T, N, D).transpose(1,2)
        v = v.view(B, T, N, D).transpose(1,2)

        # weights (B, N, T, T)
        att = q @ k.transpose(2,3) / math.sqrt(D)
        # causal mask applied to att
        att = att.masked_fill(self.mask[...,:T,:T] == 0, float('-inf'))
        # normalize att, all -inf -> 0 after softmax
        att = F.softmax(att, dim=-1)

        # attention (B, N, T, D)
        y = self.attn_dropout(att) @ v

        # gather heads and project (B, N, T, D) -> (B, T, N*D)
        attention = y.transpose(1, 2).contiguous().view(B,T,N*D)

        out = self.resid_dropout(self.c_proj(attention))
        return out


class Block(nn.Module):
    def __init__(self, h_dim, max_T, n_heads, drop_p):
        super().__init__()
        self.attn = MaskedCausalAttention(h_dim, max_T, n_heads, drop_p)
        self.mlp = nn.ModuleDict(dict(
            c_fc    = nn.Linear(h_dim, 4*h_dim),
            c_proj  = nn.Linear(4*h_dim, h_dim),
            act     = nn.GELU(),
            dropout = nn.Dropout(drop_p),
        ))
        m = self.mlp
        self.mlpf = lambda x: m.dropout(m.c_proj(m.act(m.c_fc(x)))) # MLP forward
        self.ln_1 = nn.LayerNorm(h_dim)
        self.ln_2 = nn.LayerNorm(h_dim)

    def forward(self, x):
        # Attention -> LayerNorm -> MLP -> LayerNorm
        x = x + self.attn(self.ln_1(x))
        x = x + self.mlpf(self.ln_2(x))
        return x


class DecisionTransformer(nn.Module):
    def __init__(self, state_dim, act_dim, n_blocks, h_dim, context_len, 
                 n_heads, drop_p, max_timestep=1000):
        super().__init__()

        self.state_dim = state_dim
        self.act_dim = act_dim
        self.h_dim = h_dim
        self.context_len = context_len

        ### projection heads (project to embedding)
        self.embed_timestep = nn.Sequential(nn.Embedding(max_timestep, h_dim), nn.Tanh())
        self.embed_rtg = nn.Sequential(nn.Linear(1*context_len, h_dim*context_len), nn.Tanh())
        
        # self.embed_state = nn.Linear(state_dim*context_len, h_dim*context_len)
        self.embed_state = nn.Sequential(
                            nn.Conv2d(context_len, 32, 8, stride=4, padding=0), nn.ReLU(),
                            nn.Conv2d(32, 64, 4, stride=2, padding=0), nn.ReLU(),
                            nn.Conv2d(64, 64, 3, stride=1, padding=0), nn.ReLU(),
                            nn.Flatten(), nn.Linear(3136, h_dim*context_len), nn.Tanh())
        
        self.embed_action = nn.Sequential(nn.Embedding(act_dim, h_dim), nn.Tanh())
        use_action_tanh = False # False for discrete actions

        self.embed_ln = nn.LayerNorm(h_dim)

        ### transformer blocks
        input_seq_len = 3 * context_len # 3 * context_len because we use reward, state and action as input, each is a vector of size h_dim
        self.transformer = nn.ModuleDict(dict(
            h = nn.ModuleList([Block(h_dim, input_seq_len, n_heads, drop_p) for _ in range(n_blocks)]),
            ln_f = nn.LayerNorm(h_dim),
        ))

        ### prediction heads
        self.predict_rtg = torch.nn.Linear(h_dim, 1)
        self.predict_state = torch.nn.Linear(h_dim, state_dim*state_dim)
        self.predict_action = nn.Sequential(
            *([nn.Linear(h_dim, act_dim)] + ([nn.Tanh()] if use_action_tanh else []))
        )

        # init all weights
        self.apply(self._init_weights)

        # report number of parameters (note we don't count the decoder parameters in lm_head)
        n_params = sum(p.numel() for p in self.transformer.parameters())
        print("number of parameters: %.2fM" % (n_params/1e6,))

    def _init_weights(self, module):
        if isinstance(module, (nn.Linear, nn.Embedding)):
            module.weight.data.normal_(mean=0.0, std=0.02)
            if isinstance(module, nn.Linear) and module.bias is not None:
                module.bias.data.zero_()
        elif isinstance(module, nn.LayerNorm):
            module.bias.data.zero_()
            module.weight.data.fill_(1.0)

    def forward(self, timesteps, states, actions, returns_to_go):

        B = states.shape[0] # batch size, context length, state_dim, state_dim
        T = timesteps.shape[1] # context length

        time_embeddings = self.embed_timestep(timesteps.type(torch.long)).reshape(B, T, self.h_dim)

        # time embeddings are treated similar to positional embeddings
        state_embeddings = self.embed_state(states.type(torch.float32)).reshape(B, T, self.h_dim) + time_embeddings
        action_embeddings = self.embed_action(actions.type(torch.long)).reshape(B, T, self.h_dim) + time_embeddings
        returns_embeddings = self.embed_rtg(returns_to_go.type(torch.float32)).reshape(B, T, self.h_dim) + time_embeddings

        # stack rtg, states and actions and reshape sequence as
        # (r1, s1, a1, r2, s2, a2 ...)
        x = torch.stack(
            (returns_embeddings, state_embeddings, action_embeddings), dim=1
        ).reshape(B, 3 * T, self.h_dim) # (B, 3 * T, h_dim)

        x = self.embed_ln(x)
        
        # transformer and prediction
        for block in self.transformer.h:
            x = block(x)
        h = self.transformer.ln_f(x)

        # get h reshaped such that its size = (B x 3 x T x h_dim) and
        # h[:, 0, t] is conditioned on r_0, s_0, a_0 ... r_t
        # h[:, 1, t] is conditioned on r_0, s_0, a_0 ... r_t, s_t
        # h[:, 2, t] is conditioned on r_0, s_0, a_0 ... r_t, s_t, a_t
        h = h.reshape(B, T, 3, self.h_dim).permute(0, 2, 1, 3)

        # get predictions
        return_preds = self.predict_rtg(h[:,2])     # predict next rtg given r, s, a
        state_preds = self.predict_state(h[:,2]).reshape(B, T, self.state_dim, self.state_dim)    # predict next state given r, s, a
        action_preds = self.predict_action(h[:,1])  # predict action given r, s
    
        # In the original paper, it is stated that predicting the states and returns are not necessary
        # and does not improve the performance. However, it could be an interesting study for future work.
        return state_preds, action_preds, return_preds

    @classmethod
    def from_pretrained(cls, model_type='gpt2'):
        """
        Initialize a pretrained GPT model by copying over the weights
        from a huggingface/transformers checkpoint.
        """
        assert model_type in {'gpt2', 'gpt2-medium', 'gpt2-large', 'gpt2-xl'}
        from transformers import GPT2LMHeadModel

        # create a from-scratch initialized dt model
        # config = cls.get_default_config()
        config = GPTConfig()
        model = DecisionTransformer(config)
        sd = model.transformer.state_dict()

        # init a huggingface/transformers model
        model_hf = GPT2LMHeadModel.from_pretrained(model_type)
        sd_hf = model_hf.state_dict()

        # copy while ensuring all of the parameters are aligned and match in names and shapes
        keys = [k for k in sd_hf if not k.endswith('attn.masked_bias')] # ignore these
        transposed = ['attn.c_attn.weight', 'attn.c_proj.weight', 'mlp.c_fc.weight', 'mlp.c_proj.weight']
        # basically the openai checkpoints use a "Conv1D" module, but we only want to use a vanilla nn.Linear.
        # this means that we have to transpose these weights when we import them
        # assert len(keys) == len(sd)
        for k in keys:
            if any(k.endswith(w) for w in transposed):
                # special treatment for the Conv1D weights we need to transpose
                with torch.no_grad():
                    sd[k].copy_(sd_hf[k].t())
            else:
                # vanilla copy over the other parameters
                with torch.no_grad():
                    sd[k].copy_(sd_hf[k])
        return model