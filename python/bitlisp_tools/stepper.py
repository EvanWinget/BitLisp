"""A pausable evaluator for the debugger.

The consensus evaluator keeps its state in function locals, so it
runs whole programs only. This machine keeps the same task stack,
value stack, and accrued cost as object state and executes one task
per step, which is what an interactive debugger needs: run a
little, show the stacks, run again.

The control loop reproduces machine.run exactly, ordering included:
arguments evaluate right to left, the proper-list walk precedes
every charge for an application, unknown operators are rejected
uncharged, reserved operators raise only at apply time, and the
apply cost accrues unchecked so a pre-charge error in the applied
program wins over cost_exceeded. Path lookup and reserved detection
are imported from machine rather than copied, and a differential
test pins this machine to machine.run over the vector corpus:
identical cost and result, or identical error code.

Errors are terminal state rather than escaping exceptions: a failed
step freezes the stacks for post-mortem display.
"""

from bitlisp import costs
from bitlisp.errors import BitLispError
from bitlisp.machine import APPLY, QUOTE, _is_reserved, _path_lookup
from bitlisp.operators import OPERATORS
from bitlisp.sexp import is_atom, is_pair, iter_proper_list

# Task tags, public because the display layer renders each kind
# differently. An EVAL task is (EVAL, node, env), an APPLY_OP task
# is (APPLY_OP, operator atom, argument count), an APPLY_PROGRAM
# task is (APPLY_PROGRAM, argument count).
EVAL, APPLY_OP, APPLY_PROGRAM = 0, 1, 2


class DebugMachine:
    """One evaluation, executable task by task.

    Attributes: tasks and values are the live stacks, cost the
    accrued total against max_cost, result the final node once
    evaluation succeeds, error the BitLispError once it fails.
    """

    def __init__(self, program, env, max_cost):
        self.tasks = [(EVAL, program, env)]
        self.values = []
        self.cost = 0
        self.max_cost = max_cost
        self.result = None
        self.error = None
        self._done = False

    @property
    def finished(self):
        return self._done

    def step(self):
        """Executes exactly one task.

        Raises RuntimeError when called on a finished machine, a
        caller bug: callers guard on finished. A BitLispError from
        the task becomes the terminal error state instead of
        propagating.
        """
        if self._done:
            raise RuntimeError("machine already finished")
        try:
            self._execute(self.tasks.pop())
            if not self.tasks:
                # The backstop machine.run keeps after its loop:
                # every program charges at least once, so apply cost
                # accrued unchecked is always checked before
                # completion, and this cannot fire unless a future
                # operator broke that invariant.
                if self.cost > self.max_cost:
                    raise BitLispError("cost_exceeded", "cost exceeded")
                self.result = self.values[0]
                self._done = True
        except BitLispError as exc:
            self.error = exc
            self._done = True
        except BaseException:
            # An interrupt inside a task can leave the stacks half
            # mutated, a state the consensus machine never exposes.
            # The machine finishes with neither result nor error,
            # poisoned, so no caller can keep stepping it.
            self._done = True
            raise

    def step_over(self):
        """Executes the pending task and everything it pushes.

        Runs until the task stack is back to one shorter than it
        was, the depth at which the pending task's whole subtree,
        operator application included, has completed. On a task
        that pushes nothing this is a single step.
        """
        if self._done:
            raise RuntimeError("machine already finished")
        target = len(self.tasks) - 1
        self.step()
        while not self._done and len(self.tasks) > target:
            self.step()

    def run(self):
        """Steps until the machine finishes."""
        while not self._done:
            self.step()

    def _charge(self, amount):
        self.cost += amount
        if self.cost > self.max_cost:
            raise BitLispError("cost_exceeded", "cost exceeded")

    def _accrue(self, amount):
        # Adds cost without checking the budget. The check rides on
        # the next charge, the order machine.run keeps, so an
        # uncharged error raised in between wins over cost_exceeded.
        self.cost += amount

    def _execute(self, task):
        kind = task[0]
        if kind == EVAL:
            _, node, env = task
            if is_atom(node):
                self.values.append(_path_lookup(node, env, self._charge))
                return
            op, args = node
            if is_pair(op):
                raise BitLispError("operator_not_atom", "pair in operator position")
            if op == QUOTE:
                self._charge(costs.QUOTE_COST)
                self.values.append(args)
                return
            # The proper-list walk precedes every charge for this
            # application, then unknown operators are rejected
            # uncharged, then everything else, the reserved families
            # included, charges the dispatch cost before any
            # argument evaluates. The order machine.run keeps.
            arg_list = list(iter_proper_list(args))
            if op != APPLY and op not in OPERATORS and not _is_reserved(op):
                raise BitLispError("unknown_operator", f"unknown operator {op.hex()}")
            self._charge(costs.OP_DISPATCH_COST)
            if op == APPLY:
                self.tasks.append((APPLY_PROGRAM, len(arg_list)))
            else:
                self.tasks.append((APPLY_OP, op, len(arg_list)))
            # Appending in list order makes the rightmost argument
            # evaluate first, the machine.run order, observable
            # through which failing argument reports its error.
            for arg in arg_list:
                self.tasks.append((EVAL, arg, env))
        elif kind == APPLY_OP:
            _, op, arg_count = task
            # The rightmost argument completed first, so the value
            # stack holds the arguments in reverse. The reserved
            # operator raises here, after every argument evaluated,
            # not at identification.
            args = self.values[len(self.values) - arg_count :][::-1]
            del self.values[len(self.values) - arg_count :]
            if _is_reserved(op):
                raise BitLispError("reserved_operator", "reserved operator")
            self.values.append(OPERATORS[op](args, self._charge))
        else:
            _, arg_count = task
            if arg_count != 2:
                del self.values[len(self.values) - arg_count :]
                raise BitLispError("wrong_arg_count", "apply takes 2 arguments")
            # Right-to-left evaluation puts the program result on
            # top of the value stack.
            new_program = self.values.pop()
            new_env = self.values.pop()
            self._accrue(costs.APPLY_COST)
            self.tasks.append((EVAL, new_program, new_env))
