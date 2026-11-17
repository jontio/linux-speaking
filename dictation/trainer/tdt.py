"""The TDT training loss, for a processor.

NeMo's quick version of this loss runs on NVIDIA cards only, and its plain PyTorch one
walks the grid a cell at a time (and asks for a card as well). This one does the same sum
(equation 7 of https://arxiv.org/abs/2304.06795) a frame at a time, with every text
position of a frame done at once.
"""
import torch

NEVER = -1.0e4  # the log of "can't happen"


def tdt_loss(acts, labels, act_lens, label_lens, blank, durations, sigma=0.0):
    """How unlikely each utterance's text is, as the model has it now (minus log probability).

    acts: what the joint network gives, [batch, frames, text positions + 1, tokens + 1 + durations]
    labels: the text as token numbers, [batch, text positions]
    """
    count = len(durations)
    tokens = torch.log_softmax(acts[..., :-count], -1) - sigma
    lasting = torch.log_softmax(acts[..., -count:], -1)
    batch, frames, places, _ = tokens.shape

    # An arc leaves (frame, place) by saying nothing, or by saying the next token; either
    # way it also says how many frames to move on.
    wanted = labels.long()[:, None, :, None].expand(batch, frames, places - 1, 1)
    silent = tokens[..., blank].unsqueeze(-1) + lasting                    # [B, T, U+1, D]
    spoken = tokens[:, :, :-1, :].gather(-1, wanted) + lasting[:, :, :-1]  # [B, T, U, D]
    never = acts.new_full((batch, 1), NEVER)
    stay = durations.index(0) if 0 in durations else None  # a token said without moving on

    rows = []  # rows[t][b, u]: the log probability of having reached frame t with u tokens said
    for t in range(frames):
        if t == 0:
            reached = torch.cat([acts.new_zeros((batch, 1)),
                                 acts.new_full((batch, places - 1), NEVER)], 1)
        else:
            ways = []
            for n, step in enumerate(durations):
                if step > 0 and t - step >= 0:
                    before = rows[t - step]
                    ways.append(before + silent[:, t - step, :, n])
                    ways.append(torch.cat(
                        [never, before[:, :-1] + spoken[:, t - step, :, n]], 1))
            reached = torch.logsumexp(torch.stack(ways), 0)
        if stay is not None and places > 1:
            # Tokens said one after another within this frame: each place also takes in the
            # place before it. Done as a running sum rather than place by place.
            said = torch.cat([acts.new_zeros((batch, 1)),
                              torch.cumsum(spoken[:, t, :, stay], 1)], 1)
            reached = said + torch.logcumsumexp(reached - said, 1)
        rows.append(reached)
    grid = torch.stack(rows, 1)  # [B, T, U+1]

    # The end: every token said, and a last silent arc that steps off the final frame.
    final = label_lens.long()
    answers = []
    for b in range(batch):
        ends = []
        for n, step in enumerate(durations):
            at = int(act_lens[b]) - step
            if step > 0 and at >= 0:
                ends.append(grid[b, at, final[b]] + silent[b, at, final[b], n])
        answers.append(torch.logsumexp(torch.stack(ends), 0))
    return -torch.stack(answers)
