"""The script that produces bristlecone_heatmap_example.png."""

import matplotlib.pyplot as plt
import numpy as np
import cirq


def main():
    value_map = {(qubit.row, qubit.col): np.random.random()
                 for qubit in cirq.google.known_devices.Bristlecone.qubits}

    heatmap = cirq.Heatmap(value_map)
    cirq.plot(heatmap)


if __name__ == '__main__':
    main()
