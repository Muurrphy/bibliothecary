# Visible-speech and muscle constraints

The mouth planner uses engineering constraints inspired by visible speech, including lip closure, rounding and limits on simultaneous width and opening.

## Landmarks protected by the planner

### Bilabial closure: M, B, P

The visible lips must reach closure before release. Coarticulation must not blend away the closure just because an open vowel follows.

### Labiodental contact: F, V

The lower lip moves inward/upward toward the upper teeth. A generic half-open mouth is not an adequate substitute.

### Rounding and protrusion: O, U, W

Width decreases while rounding and protrusion increase. A renderer without depth may express protrusion using contour thickness or projected scale, but the IR keeps it separate.

### Open vowels

Large opening is driven primarily by jaw/lip separation. As the mouth opens vertically, the corners cannot remain at maximum horizontal stretch.

### Diphthongs

AY, AW, OY, EY, and OW are paths, not static poses. On slow/high-resolution devices both endpoints may be visible; on a 128×64 OLED, short paths may need to retain only the most readable target.

## Antagonism

Human-like tension depends on limits, not simply larger numbers. `enforce_constraints()` prevents simultaneous extreme width and vertical opening. This rule came from repeated physical display review, but its numeric coefficients remain an engineering prior and should be evaluated against data.

## Coarticulation

Non-landmark events blend slightly toward the next target. Closure, labiodental contact, and tongue-between-teeth landmarks remain protected. The current blend is causal and uses only one event of look-ahead.

Background reading: the [JALI research project](https://www.dgp.toronto.edu/~karan/jali/) and its publications on speech animation.

## Planned evaluation

A future benchmark should include:

- M/B/P closure recall and release timing;
- F/V lower-lip placement;
- rounded-vowel error;
- large-open-vowel separation;
- width/open antagonism violations;
- jerk and minimum readable dwell;
- paired human preference tests with sample size and protocol;
- separate English, Mandarin, and Spanish profiles rather than one averaged
  map, with Spanish dialect tags reported.
