from typing import List, Set, Tuple, Sequence, Dict, Any, NamedTuple, Union
from typing import Iterable
import numpy as np
from matplotlib import pyplot as plt
from cirq import devices, ops, circuits, sim, work

CrossEntropyPair = NamedTuple('CrossEntropyPair', [('num_cycle', int),
                                                   ('xeb_fidelity', float)])


class CrossEntropyResult:
    """Results from a cross-entropy benchmarking (XEB) experiment."""

    def __init__(self, cross_entropy_pairs: Sequence[CrossEntropyPair]):
        """
        Args:
            cross_entropy_pairs: A sequence of NamedTuples, each of which
                contains two fields: num_cycle which returns the circuit
                depth as the number of cycles and xeb_fidelity which returns
                the XEB fidelity after the given cycle number.
        """
        self._data = cross_entropy_pairs

    @property
    def data(self) -> Sequence[CrossEntropyPair]:
        """Returns a sequence of CrossEntropyPairs.

        Each CrossEntropyPair is a NamedTuple that contains a cycle number and
        the corresponding XEB fidelity.
        """
        return self._data

    def plot(self, **plot_kwargs: Any) -> None:
        """Plots the average XEB fidelity vs the number of cycles.

        Args:
            **plot_kwargs: Arguments to be passed to 'matplotlib.pyplot.plot'.
        """
        num_cycles = [d.num_cycle for d in self._data]
        fidelities = [d.xeb_fidelity for d in self._data]
        fig = plt.figure()
        ax = plt.gca()
        ax.set_ylim([0, 1.1])
        plt.plot(num_cycles, fidelities, 'ro-', figure=fig, **plot_kwargs)
        plt.xlabel('Number of Cycles', figure=fig)
        plt.ylabel('XEB Fidelity', figure=fig)
        fig.show()


def cross_entropy_benchmarking(
        sampler: work.Sampler,
        qubits: Sequence[ops.Qid],
        *,
        benchmark_ops: Sequence[ops.Moment] = None,
        num_circuits: int = 20,
        repetitions: int = 1000,
        cycles: Union[int, Iterable[int]] = range(2, 103, 10),
        scrambling_gates_per_cycle: List[List[ops.SingleQubitGate]] = None,
        simulator: sim.Simulator = None,
) -> CrossEntropyResult:
    r"""Cross-entropy benchmarking (XEB) of multiple qubits.

    A total of M random circuits are generated, each of which comprises N
    layers where N = max('cycles') or 'cycles' if a single value is specified
    for the 'cycles' parameter. Every layer contains randomly generated
    single-qubit gates applied to each qubit, followed by a set of
    user-defined benchmarking operations (e.g. a set of two-qubit gates).

    Each circuit (circuit_m) from the M random circuits is further used to
    generate a set of circuits {circuit_mn}, where circuit_mn is built from the
    first n cycles of circuit_m. n spans all the values in 'cycles'.

    For each fixed value n, the experiment performs the following:

    1) Experimentally collect a number of bit-strings for each circuit_mn via
    projective measurements in the z-basis.

    2) Theoretically compute the expected bit-string probabilities
    $P^{th, mn}_|...00>$,  $P^{th, mn}_|...01>$, $P^{th, mn}_|...10>$,
    $P^{th, mn}_|...11>$ ... at the end of circuit_mn for all m and for all
    possible bit-strings in the Hilbert space.

    3) Compute an experimental XEB function for each circuit_mn:

    $f_{mn}^{meas} = \langle D * P^{th, mn}_q - 1 \rangle$

    where D is the number of states in the Hilbert space, $P^{th, mn}_q$ is the
    theoretical probability of a bit-string q at the end of circuit_mn, and
    $\langle \rangle$ corresponds to the ensemble average over all measured
    bit-strings.

    Then, take the average of $f_{mn}^{meas}$ over all circuit_mn with fixed
    n to obtain:

    $f_{n} ^ {meas} = (\sum_m f_{mn}^{meas}) / M$

    4) Compute a theoretical XEB function for each circuit_mn:

    $f_{mn}^{th} = D \sum_q (P^{th, mn}_q) ** 2 - 1$

    where the summation goes over all possible bit-strings q in the Hilbert
    space.

    Similarly, we then average $f_m^{th}$ over all circuit_mn with fixed n to
    obtain:

    $f_{n} ^ {th} = (\sum_m f_{mn}^{th}) / M$

    5) Calculate the XEB fidelity $\alpha_n$ at fixed n:

    $\alpha_n = f_{n} ^ {meas} / f_{n} ^ {th}$

    Args:
        sampler: The quantum engine or simulator to run the circuits.
        qubits: The qubits included in the XEB experiment.
        benchmark_ops: A sequence of ops.Moment containing gate operations
            between specific qubits which are to be benchmarked for fidelity.
            If more than one ops.Moment is specified, the random circuits
            will rotate between the ops.Moment's. As an example,
            if benchmark_ops = [Moment([ops.CZ(q0, q1), ops.CZ(q2, q3)]),
            Moment([ops.CZ(q1, q2)]) where q0, q1, q2 and q3 are instances of
            Qid (such as GridQubits), each random circuit will apply CZ gate
            between q0 and q1 plus CZ between q2 and q3 for the first cycle,
            CZ gate between q1 and q2 for the second cycle, CZ between q0 and
            q1 and CZ between q2 and q3 for the third cycle and so on. If
            None, the circuits will consist only of single-qubit gates.
        num_circuits: The total number of random circuits to be used.
        repetitions: The number of measurements for each circuit to estimate
            the bit-string probabilities.
        cycles: The different numbers of circuit layers in the XEB study.
            Could be a single or a collection of values.
        scrambling_gates_per_cycle: If None (by default), the single-qubit
            gates are chosen from X/2 ($\pi/2$ rotation around the X axis),
            Y/2 ($\pi/2$ rotation around the Y axis) and (X + Y)/2 ($\pi/2$
            rotation around an axis $\pi/4$ away from the X on the equator of
            the Bloch sphere). Otherwise the single-qubit gates for each layer
            are chosen from a list of possible choices (each choice is a list
            of one or more single-qubit gates).
        simulator: A simulator that calculates the bit-string probabilities
            of the ideal circuit. By default, this is set to sim.Simulator().

    Returns:
        A CrossEntropyResult object that stores and plots the result.
    """
    simulator = sim.Simulator() if simulator is None else simulator
    num_qubits = len(qubits)

    if isinstance(cycles, int):
        cycle_range = [cycles]
    else:
        cycle_range = list(cycles)

    # These store the measured and simulated bit-string probabilities from
    # all trials in two dictionaries. The keys of the dictionaries are the
    # numbers of cycles. The values are 2D arrays with each row being the
    # probabilities obtained from a single trial.
    probs_meas = {
        n: np.zeros((num_circuits, 2**num_qubits)) for n in cycle_range
    }
    probs_exp = {
        n: np.zeros((num_circuits, 2**num_qubits)) for n in cycle_range
    }

    for k in range(num_circuits):

        # Generates one random XEB circuit with max(num_cycle_range) cycles.
        # Then the first n cycles of the circuit are taken to generate
        # shorter circuits with n cycles (n taken from cycles). All of these
        # circuits are stored in circuits_k.
        circuits_k = _build_xeb_circuits(qubits, cycle_range,
                                         scrambling_gates_per_cycle,
                                         benchmark_ops)

        # Run each circuit with the sampler to obtain a collection of
        # bit-strings, from which the bit-string probabilities are estimated.
        probs_meas_k = _measure_prob_distribution(sampler, repetitions, qubits,
                                                  circuits_k)

        # Simulate each circuit with the Cirq simulator to obtain the
        # wavefunction at the end of each circuit, from which the
        # theoretically expected bit-string probabilities are obtained.
        probs_exp_k = []  # type: List[np.ndarray]
        for circ_k in circuits_k:
            res = simulator.simulate(circ_k, qubit_order=qubits)
            state_probs = np.abs(np.asarray(res.final_state)  # type: ignore
                                )**2
            probs_exp_k.append(state_probs)

        for i, num_cycle in enumerate(cycle_range):
            probs_exp[num_cycle][k, :] = probs_exp_k[i]
            probs_meas[num_cycle][k, :] = probs_meas_k[i]

    fidelity_vals = _xeb_fidelities(probs_exp, probs_meas)
    xeb_data = [
        CrossEntropyPair(c, k) for (c, k) in zip(cycle_range, fidelity_vals)
    ]
    return CrossEntropyResult(xeb_data)


def build_entangling_layers(qubits: Sequence[devices.GridQubit],
                            two_qubit_gate: ops.TwoQubitGate
                           ) -> List[ops.Moment]:
    """Builds a sequence of gates that entangle all pairs of qubits on a grid.

    The qubits are restricted to be physically on a square grid with distinct
    row and column indices (not every node of the grid needs to have a
    qubit). To entangle all pairs of qubits, a user-specified two-qubit gate
    is applied between each and every pair of qubit that are next to each
    other. In general, a total of four sets of parallel operations are needed to
    perform all possible two-qubit gates. We proceed as follows:

    The first layer applies two-qubit gates to qubits (i, j) and (i, j + 1)
    where i is any integer and j is an even integer. The second layer
    applies two-qubit gates to qubits (i, j) and (i + 1, j) where i is an even
    integer and j is any integer. The third layer applies two-qubit gates
    to qubits (i, j) and (i, j + 1) where i is any integer and j is an odd
    integer. The fourth layer applies two-qubit gates to qubits (i, j) and
    (i + 1, j) where i is an odd integer and j is any integer.

    After the layers are built as above, any empty layer is ejected.:

                 Cycle 1:                            Cycle 2:
        q00 ── q01    q02 ── q03            q00    q01    q02    q03
                                             |      |      |      |
        q10 ── q11    q12 ── q13            q10    q11    q12    q13

        q20 ── q21    q22 ── q23            q20    q21    q22    q23
                                             |      |      |      |
        q30 ── q31    q32 ── q33            q30    q31    q32    q33

                  Cycle 3:                           Cycle 4:
        q00    q01 ── q02    q03            q00    q01    q02    q03

        q10    q11 ── q12    q13            q10    q11    q12    q13
                                             |      |      |      |
        q20    q21 ── q22    q23            q20    q21    q22    q23

        q30    q31 ── q32    q33            q30    q31    q32    q33

    Args:
        qubits: The grid qubits included in the entangling operations.
        two_qubit_gate: The two-qubit gate to be applied between all
            neighboring pairs of qubits.

    Returns:
        A list of ops.Moment, with a maximum length of 4. Each ops.Moment
        includes two-qubit gates which can be performed at the same time.
    """
    interaction_sequence = _default_interaction_sequence(qubits)
    return [
        ops.Moment([two_qubit_gate(q_a, q_b)
                    for (q_a, q_b) in pairs])
        for pairs in interaction_sequence
    ]


def _build_xeb_circuits(
        qubits: Sequence[ops.Qid],
        cycles: Sequence[int],
        single_qubit_gates: List[List[ops.SingleQubitGate]] = None,
        benchmark_ops: Sequence[ops.Moment] = None,
) -> List[circuits.Circuit]:
    if benchmark_ops is not None:
        num_d = len(benchmark_ops)
    else:
        num_d = 0
    max_cycles = max(cycles)

    if single_qubit_gates is None:
        single_rots = _random_half_rotations(qubits, max_cycles)
    else:
        single_rots = _random_any_gates(qubits, single_qubit_gates, max_cycles)
    all_circuits = []  # type: List[circuits.Circuit]
    for num_cycles in cycles:
        circuit_exp = circuits.Circuit()
        for i in range(num_cycles):
            circuit_exp.append(single_rots[i])
            if benchmark_ops is not None:
                for op_set in benchmark_ops[i % num_d]:
                    circuit_exp.append(op_set)
        all_circuits.append(circuit_exp)
    return all_circuits


def _measure_prob_distribution(sampler: work.Sampler, repetitions: int,
                               qubits: Sequence[ops.Qid],
                               circuit_list: List[circuits.Circuit]
                              ) -> List[np.ndarray]:
    all_probs = []  # type: List[np.ndarray]
    num_states = 2**len(qubits)
    for circuit in circuit_list:
        trial_circuit = circuit.copy()
        trial_circuit.append(ops.measure(*qubits, key='z'))
        res = sampler.run(trial_circuit, repetitions=repetitions)
        res_hist = dict(res.histogram(key='z'))
        probs = np.zeros(num_states, dtype=float)
        for k, v in res_hist.items():
            probs[k] = float(v) / float(repetitions)
        all_probs.append(probs)
    return all_probs


def _xeb_fidelities(ideal_probs: Dict[int, np.ndarray],
                    actual_probs: Dict[int, np.ndarray]) -> List[float]:
    num_cycles = sorted(list(ideal_probs.keys()))
    return [
        _compute_fidelity(ideal_probs[n], actual_probs[n]) for n in num_cycles
    ]


def _compute_fidelity(probs_exp: np.ndarray, probs_meas: np.ndarray) -> float:
    _, num_states = probs_exp.shape
    pp_cross = probs_exp * probs_meas
    pp_exp = probs_exp**2
    f_meas = np.mean(num_states * np.sum(pp_cross, axis=1) - 1.0)
    f_exp = np.mean(num_states * np.sum(pp_exp, axis=1) - 1.0)
    return float(f_meas / f_exp)


def _random_half_rotations(qubits: Sequence[ops.Qid],
                           num_layers: int) -> List[List[ops.OP_TREE]]:
    rot_ops = [
        ops.X**0.5, ops.Y**0.5,
        ops.PhasedXPowGate(phase_exponent=0.25, exponent=0.5)
    ]
    num_qubits = len(qubits)
    rand_nums = np.random.choice(3, (num_qubits, num_layers))
    single_q_layers = []  # type: List[List[ops.OP_TREE]]
    for i in range(num_layers):
        single_q_layers.append(
            [rot_ops[rand_nums[j, i]](qubits[j]) for j in range(num_qubits)])
    return single_q_layers


def _random_any_gates(qubits: Sequence[ops.Qid],
                      op_list: List[List[ops.SingleQubitGate]],
                      num_layers: int) -> List[List[ops.OP_TREE]]:
    num_ops = len(op_list)
    num_qubits = len(qubits)
    rand_nums = np.random.choice(num_ops, (num_qubits, num_layers))
    single_q_layers = []  # type: List[List[ops.OP_TREE]]
    for i in range(num_layers):
        rots_i = []  # type: List[ops.OP_TREE]
        for j in range(num_qubits):
            rots_i.extend([rot(qubits[j]) for rot in op_list[rand_nums[j, i]]])
        single_q_layers.append(rots_i)
    return single_q_layers


def _default_interaction_sequence(
        qubits: Sequence[devices.GridQubit]
) -> List[Set[Tuple[devices.GridQubit, devices.GridQubit]]]:
    qubit_dict = {(qubit.row, qubit.col): qubit for qubit in qubits}
    qubit_locs = set(qubit_dict)
    num_rows = max([q.row for q in qubits]) + 1
    num_cols = max([q.col for q in qubits]) + 1

    l_s = [set() for _ in range(4)
          ]  # type: List[Set[Tuple[devices.GridQubit, devices.GridQubit]]]
    for i in range(num_rows):
        for j in range(num_cols - 1):
            if (i, j) in qubit_locs and (i, j + 1) in qubit_locs:
                l_s[j % 2 * 2].add((qubit_dict[(i, j)], qubit_dict[(i, j + 1)]))

    for i in range(num_rows - 1):
        for j in range(num_cols):
            if (i, j) in qubit_locs and (i + 1, j) in qubit_locs:
                l_s[i % 2 * 2 + 1].add(
                    (qubit_dict[(i, j)], qubit_dict[(i + 1, j)]))

    l_final = []  # type: List[Set[Tuple[devices.GridQubit, devices.GridQubit]]]
    for gate_set in l_s:
        if len(gate_set) != 0:
            l_final.append(gate_set)

    return l_final
