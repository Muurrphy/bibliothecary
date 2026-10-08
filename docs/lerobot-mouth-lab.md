# Future LeRobot soft-mouth lab

This is a future validation track, not a prerequisite for the software release.

The research question is narrow:

> Given a correct Articulation IR trajectory, how accurately can a low-cost 4–6 DoF silicone mouth execute it under hysteresis, coupling, speed, and force limits?

## Integration strategy

Do not use a complete SO-101 arm to pull lips with its end effector and do not dismantle the arm. Keep SO-101 as the standard learning platform. Implement the mouth rig as an external LeRobot hardware plugin, tentatively named `lerobot_robot_lilyput_mouth`.

LeRobot's official custom-hardware interface supports arbitrary robot form factors with programmatic observations and actions: [Bring Your Own Hardware](https://huggingface.co/docs/lerobot/main/en/integrate_hardware).

## 4-DoF minimum

1. jaw opening;
2. left corner;
3. right corner;
4. round/protrude.

## 6-DoF extension

Add upper-lip and lower-lip vertical/tuck control. The final count should be justified by 1/3/4/6-DoF ablation, not by the number of spare motors.

## Data

Each frame should include fixed-camera RGB, motor position/velocity/temperature/load when available, previous action, target Articulation IR, phoneme/time, silicone specimen ID, calibration version, and safety state.

## Training order

1. material coupons and anchor tear tests;
2. safe limits and low-force motor babbling;
3. forward model from motor history to visible keypoints;
4. constrained inverse control or MPC;
5. learned temporal residual only if it beats static baselines;
6. real speech on the same audio-motion clock.

## Baselines

- volume-only jaw opening;
- hand-authored phoneme-to-servo map;
- static learned inverse;
- temporal model;
- temporal model with visual feedback.

The output should be a reproducible low-cost reference platform and dataset, not a claim to outperform Columbia's higher-DOF face in general realism.
