# Kafka consumer with following responsibilities:
# - Read feature vector from Kafka topic.
# - Compute vector hash via LSH.
# - Publish vector hash to topic.

from confluent_kafka import Consumer, KafkaError, Producer
from time import time
import numpy as np
import pdb
import os


class SimpleLSH(object):

    def __init__(self, seed=865, bits=1024):
        self.bits = bits
        self.rng = np.random.RandomState(seed)
        self.planes = None
        self.M = None
        self.N = None
        self.NdotM = None

    def save(self, model_path):
        np.savez(model_path, self.M, self.N, self.NdotM)
        return self

    def load(self, model_path):
        arrs = np.load(model_path)
        self.M = arrs['arr_0']
        self.N = arrs['arr_1']
        self.NdotM = arrs['arr_2']
        return self

    def fit(self, X):
        sample_ii = self.rng.choice(range(len(X)), 2 * self.bits)
        X_sample = X[sample_ii].reshape(2, self.bits, X.shape[-1])
        self.M = (X_sample[0, ...] + X_sample[1, ...]) / 2
        self.N = X_sample[-1, ...] - self.M
        self.NdotM = (self.N * self.M).sum(-1)
        return self

    def get_vector_hash(self, X):
        XdotN = X.dot(self.N.T)
        return (XdotN >= self.NdotM).astype(np.uint8)


if __name__ == "__main__":

    K_SERVER = "localhost:9092"
    K_SUB_TOPIC = "glove-feature-vectors"
    K_PUB_TOPIC = "glove-hash-vectors"

    settings = {
        'bootstrap.servers': K_SERVER,
        'group.id': 'TODO',
        'client.id': 'client-%d' % time(),
        'enable.auto.commit': True,
        'session.timeout.ms': 6000,
        'default.topic.config': {
            'auto.offset.reset': 'smallest'
        }
    }

    consumer = Consumer(settings)
    producer = Producer({"bootstrap.servers": K_SERVER})
    consumer.subscribe([K_SUB_TOPIC])

    glove_dir = '/home/alex/dev/approximate-vector-search/scratch/es-lsh-glove'
    vecs = np.load('%s/glove_vecs.npy' % glove_dir).astype(np.float32)
    simple_lsh = SimpleLSH(bits=1024, seed=865)
    simple_lsh.fit(vecs)

    while True:

        # TODO: is it really best practice to poll like this?
        msg = consumer.poll(0.1)
        if msg is None:
            continue

        if msg.error():
            print('Error: %s' % msg.error().str())
            continue

        key = msg.key().decode()
        vec = np.fromstring(msg.value(), dtype=np.float32)
        hsh = simple_lsh.get_vector_hash(vec[np.newaxis, :])

        print('%s %s %.3lf %s %.3lf' % (
            key, str(vec.shape), vec.mean(), str(hsh.shape), hsh.mean()))

        producer.produce(K_PUB_TOPIC, key=key, value=hsh.tostring())

    # TODO: use atexit to make sure it flushes if the script fails.
    producer.flush()
