# Copyright 2019 DeepMind Technologies Ltd. All rights reserved.
# Copyright 2021 Artificial Intelligence Center, Czech Techical University
# Copied and adapted from OpenSpiel (https://github.com/deepmind/open_spiel)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl import app
from absl import flags
from absl import logging
import tensorflow.compat.v1 as tf

from open_spiel.python.algorithms import rcfr
import pyspiel

tf.enable_eager_execution()

FLAGS = flags.FLAGS

flags.DEFINE_integer("iterations", 100000, "Number of training iterations.")
flags.DEFINE_string("game", "kuhn_poker", "Name of the game")
flags.DEFINE_integer("players", 2, "Number of players")
flags.DEFINE_integer("logfreq", 100, "How often to print the exploitability")

flags.DEFINE_boolean("bootstrap", False,
                     "Whether or not to use bootstrap targets")
flags.DEFINE_boolean("truncate_negative", False,
                     "Whether or not to truncate negative targets to zero")
flags.DEFINE_integer(
    "buffer_size", -1,
    "A reservoir buffer size. A non-positive size implies an effectively "
    "infinite buffer.")
flags.DEFINE_integer("num_hidden_layers", 1,
                     "The number of hidden layers in the regret model.")
flags.DEFINE_integer("num_hidden_units", 13,
                     "The number of hidden layers in the regret model.")
flags.DEFINE_integer(
    "num_hidden_factors", 8,
    "The number of factors in each hidden layer in the regret model.")
flags.DEFINE_boolean(
    "use_skip_connections", True,
    "Whether or not to use skip connections in the regret model.")
flags.DEFINE_integer(
    "num_epochs", 200,
    "The number of epochs to run between each iterations to update the regret "
    "models.")
flags.DEFINE_integer(
    "batch_size", 100, "The regret model training batch size.")
flags.DEFINE_float("step_size", 0.01,
                   "The ADAM (AMSGrad) optimizer step size.")
flags.DEFINE_string("project", "openspiel", "project name")
flags.DEFINE_boolean("no_wandb", False, "Disables Weights & Biases")


def main(argv):
    if not FLAGS.no_wandb:
        import wandb
        wandb.init(project=FLAGS.project)
        wandb.config.update(flags.FLAGS)
        wandb.config.update({"solver": "rcfr"})

    game = pyspiel.load_game(
        FLAGS.game, {"players": pyspiel.GameParameter(FLAGS.players)})

    models = []
    for _ in range(game.num_players()):
        models.append(
            rcfr.DeepRcfrModel(
                game,
                num_hidden_layers=FLAGS.num_hidden_layers,
                num_hidden_units=FLAGS.num_hidden_units,
                num_hidden_factors=FLAGS.num_hidden_factors,
                use_skip_connections=FLAGS.use_skip_connections))

    if FLAGS.buffer_size > 0:
        solver = rcfr.ReservoirRcfrSolver(
            game,
            models,
            FLAGS.buffer_size,
            truncate_negative=FLAGS.truncate_negative)
    else:
        solver = rcfr.RcfrSolver(
            game,
            models,
            truncate_negative=FLAGS.truncate_negative,
            bootstrap=FLAGS.bootstrap)

    def _train_fn(model, data):
        """Train `model` on `data`."""
        data = data.shuffle(FLAGS.batch_size * 10)
        data = data.batch(FLAGS.batch_size)
        data = data.repeat(FLAGS.num_epochs)

        optimizer = tf.keras.optimizers.Adam(lr=FLAGS.step_size, amsgrad=True)

        @tf.function
        def _train():
            for x, y in data:
                optimizer.minimize(
                    lambda: tf.losses.huber_loss(
                        y, model(x), delta=0.01),  # pylint: disable=cell-var-from-loop
                    model.trainable_variables)

        _train()

    for i in range(FLAGS.iterations):
        solver.evaluate_and_update_policy(_train_fn)

        if i % FLAGS.logfreq == 0:
            expl = pyspiel.exploitability(game, solver.average_policy())
            logging.info("Iteration: {} Exploitability: {}".format(i, expl))

            if not FLAGS.no_wandb:
                wandb.log({"Iteration": i, 'Exploitability': expl})


if __name__ == "__main__":
    app.run(main)
