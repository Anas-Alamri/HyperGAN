import tensorflow as tf
import numpy as np
import hyperchamber as hc
import inspect
import collections

from tensorflow.python.ops import math_ops
from hypergan.trainers.base_trainer import BaseTrainer
from tensorflow.python.ops import gradients_impl

TINY = 1e-12

cg_state = collections.namedtuple("CGState", ["i", "x", "r", "p", "rdotr"])
def update_vars(state1, state2):
  ops = []
  for name in state1._fields:
    state1_vs = getattr(state1, name)
    if isinstance(state1_vs, list):
      ops += [tf.assign(_v1, _v2) for _v1, _v2 in zip(state1_vs, getattr(state2, name))]
    else:
      ops += [tf.assign(state1_vs, getattr(state2, name))]
  return tf.group(*ops)

def build_vars(state):
  args = []
  variables = []
  for name in state._fields:
    vs = getattr(state, name)
    if isinstance(vs, list):
        sv = [tf.Variable(tf.zeros_like(v), trainable=False, name=name+"_sv_dontsave") for v in vs]
        variables += sv
    else:
        sv = tf.Variable(tf.zeros_like(vs), trainable=False, name=name+"_sv_dontsave")
        variables += [sv]
    args.append(sv)
  return cg_state(*args), variables

def tf_conjugate_gradient(operator,
                       rhs,
                       tol=1e-4,
                       max_iter=20,
                       name="conjugate_gradient"):
    r"""
        modified from tensorflow/contrib/solvers/python/ops/linear_equations.py
    """
    def dot(x, y):
      return tf.reduce_sum(tf.multiply(x,y))

    def cg_step(state):  # pylint: disable=missing-docstring
      #z = [p * h2 for p, h2 in zip(state.p, operator.apply(state.p))]
      z = operator.apply(state.p)

      alpha = [_r / (dot(_p, _p+_z)+1e-12) for _r, _p, _z in zip(state.rdotr, state.p, z)]
      x = [_alpha * _p + _x for _alpha, _p, _x in zip(alpha, state.p, state.x)]

      r = [-_alpha * (_z+_p) + _r for _alpha, _z,_r,_p in zip(alpha, z, state.r, state.p)]
      new_rdotr = [dot(_r, _r) for _r in r]
      beta = [_new_rdotr / (_rdotr+1e-12) for _new_rdotr, _rdotr in zip(new_rdotr, state.rdotr)]
      p = [_r + _beta * _p for _r, _beta, _p in zip(r,beta,state.p)]
      i = state.i + 1

      return cg_state(i, x, r, p, new_rdotr)

    with tf.name_scope(name):
      x = [tf.zeros_like(h) for h in rhs]
      rdotr = [dot(_r, _r) for _r in rhs]
      state = cg_state(i=0, x=x, r=rhs, p=rhs, rdotr=rdotr)
      state, variables = build_vars(state)
      def update_op(state):
        return update_vars(state, cg_step(state))
      def reset_op(state, rhs):
        return update_vars(state, cg_step(cg_state(i=0, x=x, r=rhs, p=rhs, rdotr=rdotr)))
      return [reset_op(state, rhs), update_op(state), variables, state]

class CGOperator:
    def __init__(self, hvp, x_loss, y_loss, x_params, y_params, lr):
        self.hvp = hvp
        self.x_loss = x_loss
        self.y_loss = y_loss
        self.x_params = x_params
        self.y_params = y_params
        self.lr = lr

    def apply(self, p):
        lr_x = tf.sqrt(self.lr)
        lr_y = self.lr
        h_1_v = self.hvp(self.x_loss, self.y_params, self.x_params, [lr_x * _p for _p in p])
        for _x, _h in zip(self.x_params, h_1_v):
            if _h is None:
                print("X none", _x)
        return [lr_x * _x for _x in self.hvp(self.y_loss, self.x_params, self.y_params, [lr_y * _h for _h in h_1_v])]

class CompetitiveTrainer(BaseTrainer):
    def hessian_vector_product(self, ys, xs, xs2, vs, grads=None):
        if len(vs) != len(xs):
            raise ValueError("xs and v must have the same length.")

        if grads is None:
            grads = tf.gradients(ys, xs)

        assert len(grads) == len(xs)
        elemwise_products = [
                math_ops.multiply(grad_elem, tf.stop_gradient(v_elem))
                for grad_elem, v_elem in zip(grads, vs)
                if grad_elem is not None
                ]

        return tf.gradients(elemwise_products, xs2)

    def _create(self):
        gan = self.gan
        config = self.config
        lr = self.config.learn_rate

        loss = self.gan.loss
        d_loss, g_loss = loss.sample

        config.optimizer["loss"] = loss.sample

        self.optimizer = self.gan.create_optimizer(config.optimizer)

        d_grads = tf.gradients(d_loss, gan.d_vars())
        g_grads = tf.gradients(g_loss, gan.g_vars())

        self.g_loss = g_loss
        self.d_loss = d_loss
        self.gan.trainer = self

        d_params = gan.d_vars()
        g_params = gan.g_vars()
        clarified_d_grads = [tf.Variable(tf.zeros_like(v), trainable=False, name=v.name.split(":")[0]+"_sv_dontsave") for v in d_grads]
        clarified_g_grads = [tf.Variable(tf.zeros_like(v), trainable=False, name=v.name.split(":")[0]+"_sv_dontsave") for v in g_grads]

        clarified_grads = clarified_d_grads + clarified_g_grads
        operator_g = CGOperator(hvp=self.hessian_vector_product, x_loss=d_loss, y_loss=g_loss, x_params=d_params, y_params=g_params, lr=lr)
        reset_g_op, cg_g_op, var_g, state_g = tf_conjugate_gradient( operator_g, clarified_g_grads, max_iter=(self.config.nsteps or 10) )
        operator_d = CGOperator(hvp=self.hessian_vector_product, x_loss=g_loss, y_loss=d_loss, x_params=g_params, y_params=d_params, lr=lr)
        reset_d_op, cg_d_op, var_d, state_d = tf_conjugate_gradient( operator_d, clarified_d_grads, max_iter=(self.config.nsteps or 10) )
        self._variables = var_g + var_d + clarified_g_grads + clarified_d_grads

        assign_d = [tf.assign(c, x) for c, x in zip(clarified_d_grads, d_grads)]
        assign_g = [tf.assign(c, y) for c, y in zip(clarified_g_grads, g_grads)]
        self.reset_clarified_gradients = tf.group(*(assign_d+assign_g))

        self.reset_conjugate_tracker = tf.group(reset_g_op, reset_d_op)
        self.conjugate_gradient_descend_t_1 = tf.group(cg_g_op, cg_d_op)

        assign_d2 = [tf.assign(c, x) for c, x in zip(clarified_d_grads, state_d.x)]
        assign_g2 = [tf.assign(c, y) for c, y in zip(clarified_g_grads, state_g.x)]

        self.conjugate_gradient_descend_t_2 = tf.group(*(assign_d2+assign_g2))
        self.gan.add_metric('cg_g', sum([ tf.reduce_sum(tf.abs(_p)) for _p in clarified_g_grads]))

        if self.config.sga_lambda:
            dyg = tf.gradients(g_loss, g_params)
            dxf = tf.gradients(d_loss, d_params)
            hyp_d = self.hessian_vector_product(d_loss, g_params, d_params, [self.config.sga_lambda * _g for _g in dyg])
            hyp_g = self.hessian_vector_product(g_loss, d_params, g_params, [self.config.sga_lambda * _g for _g in dxf])
            sga_g_op = [tf.assign_sub(_g, _h) for _g, _h in zip(clarified_g_grads, hyp_g)]
            sga_d_op = [tf.assign_sub(_g, _h) for _g, _h in zip(clarified_d_grads, hyp_d)]
            self.sga_step_t = tf.group(*(sga_d_op + sga_g_op))
            self.gan.add_metric('hyp_g', sum([ tf.reduce_mean(_p) for _p in hyp_g]))
            self.gan.add_metric('hyp_d', sum([ tf.reduce_mean(_p) for _p in hyp_d]))

        #self.clarification_metric_g = sum(state_g.rdotr)
        #self.clarification_metric_d = sum(state_d.rdotr)
        def _metric(r):
            #return tf.reduce_max(tf.convert_to_tensor([tf.reduce_max(tf.norm(_r)) for _r in r]))
            return [tf.reduce_max(tf.norm(_r)) for _r in r][0]
        self.clarification_metric_g = _metric(state_g.r)
        self.clarification_metric_d = _metric(state_d.r)

        all_vars = d_params + g_params
        new_grads_and_vars = list(zip(clarified_grads, all_vars)).copy()
    

        self.optimize_t = self.optimizer.apply_gradients(new_grads_and_vars)

    def required(self):
        return "".split()

    def variables(self):
        return super().variables() + self._variables

    def _step(self, feed_dict):
        gan = self.gan
        sess = gan.session
        config = self.config
        loss = gan.loss
        metrics = gan.metrics()

        d_loss, g_loss = loss.sample

        self.before_step(self.current_step, feed_dict)
        sess.run(self.reset_clarified_gradients, feed_dict)
        sess.run(self.reset_conjugate_tracker, feed_dict)
        i=0

        if self.config.sga_lambda:
            sess.run(self.sga_step_t, feed_dict)

        while True:
            i+=1
            mx, my, _ = sess.run([self.clarification_metric_d, self.clarification_metric_g, self.conjugate_gradient_descend_t_1], feed_dict)
            if i == 1:
                initial_clarification_metric_g = my
                initial_clarification_metric_d = mx

            threshold = my / (initial_clarification_metric_g+1e-12) + mx / (initial_clarification_metric_d+1e-12)

            if self.config.log_level == "info":
                print("-MD %e MG %e" % (mx, my))
            if self.config.max_steps and i > self.config.max_steps:
               if self.config.verbose:
                   print("Max steps ", self.config.max_steps, "threshold", threshold, "max", self.config.threshold)
               break
            if threshold < (self.config.threshold or 0.9): # must be < 0.9 * initial
                   sess.run(self.conjugate_gradient_descend_t_2)
                   if self.config.verbose:
                       print("Found in ", i, "threshold", threshold)
                   break
        metric_values = sess.run([self.optimize_t] + self.output_variables(metrics), feed_dict)[1:]
        self.after_step(self.current_step, feed_dict)

        if self.current_step % 10 == 0:
            print(str(self.output_string(metrics) % tuple([self.current_step] + metric_values)))

