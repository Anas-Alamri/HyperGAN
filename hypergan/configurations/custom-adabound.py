{
  "description":"Custom adabound 256x256",
  "publication":"",
  "discriminator": 
  {
    "class": "class:hypergan.discriminators.configurable_discriminator.ConfigurableDiscriminator",
    "initializer": "he_normal",
    "defaults":{
      "activation": "lrelu",
      "initializer": "he_normal",
      "filter": [3,3],
      "stride": [1,1],
      "avg_pool": [2,2]
    },
    "layers":[
      "conv 32 name=d1",
      "conv 64 name=discriminator_4",
      "conv 128 name=discriminator_7",
      "conv 256 name=discriminator_10",
      "conv 512 name=discriminator_13",
      "linear 1 name=discriminator_16 activation=null bias=false initializer=stylegan"
    ]
  },
  "generator": {
    "class": "class:hypergan.discriminators.configurable_discriminator.ConfigurableDiscriminator",
    "defaults": {
      "activation": "lrelu",
      "initializer": "he_normal",
      "filter": [3,3],
      "stride": [1,1],
      "avg_pool": [1,1]
    },
    "layers": [
      ["linear 512 initializer=stylegan", "linear 512 initializer=stylegan name=w"],
      "linear 4*4*512 initializer=stylegan",

      "adaptive_instance_norm",
      "subpixel 128",
      "adaptive_instance_norm",
      "subpixel 128",
      "adaptive_instance_norm",
      "subpixel 64",
      "adaptive_instance_norm",
      "subpixel 32",
      "adaptive_instance_norm",
      "subpixel 16",
      "adaptive_instance_norm",
      "subpixel 3 activation=clamped_unit"
    ]
  },
  "latent": {
    "class": "function:hypergan.distributions.uniform_distribution.UniformDistribution",
    "max": 1,
    "min": -1,
    "projections": [
      "function:hypergan.distributions.uniform_distribution.identity"
    ],
    "z": 128
  },
  "loss": {
    "class": "function:hypergan.losses.logistic_loss.LogisticLoss",
    "reduce": "reduce_mean"
  },
    "trainer": {
      "class": "function:hypergan.trainers.batch_fitness_trainer.BatchFitnessTrainer",
      "search_steps": 25,
  "trainer": {
    "class": "function:hypergan.trainers.simultaneous_trainer.SimultaneousTrainer",
            "optimizer": {
        "class": "function:hypergan.optimizers.curl_optimizer.CurlOptimizer",
        "learn_rate": 0.00001,
        "d_rho": 1.0,
        "g_rho": 1.0,

    "optimizer": {

        "class": "function:hypergan.optimizers.elastic_weight_consolidation_optimizer.ElasticWeightConsolidationOptimizer",
        "f_decay": 0.85,
        "initial_constraint": 0.1,
        "add_ewc_loss_gradients": true,
        "gradient_scale": 1.0,
        "lam": 20.0,
          "optimizer": {
            "class": "function:hypergan.optimizers.experimental.ema_optimizer.EmaOptimizer",
            "decay": 0.8,

          "optimizer": {
            "class": "function:hypergan.optimizers.AdaBound.AdaBoundOptimizer",
              "beta1": 0.0,
            "beta2": 0.999,
              "learn_rate": 5e-3,
            "lower_bound":-1,
            "upper_bound":-1
          }
          }
    }
    },
    "hooks":[
      {
        "class": "function:hypergan.train_hooks.experimental.input_fitness_train_hook.InputFitnessTrainHook",
        "search_steps": 9
      },
      {
        "class": "function:hypergan.train_hooks.experimental.adversarial_robust_train_hook.AdversarialRobustTrainHook",
        "lambda": 1000.0,
        "v_lambda": -100.0
      }
    ]
  }

  },
  
  "runtime": {
      "channels": 3,
      "width": 128,
      "height": 128,
      "train": "hypergan train [dataset] --sample_every 100 --sampler debug --format jpg --size 128x128x3 -b 1 -c stylegan --save_every 10000 --resize"
  },
  "fixed_input": true,

  "class": "class:hypergan.gans.standard_gan.StandardGAN"
}
