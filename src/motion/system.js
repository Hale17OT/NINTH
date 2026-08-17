export const motionEase = [0.16, 1, 0.3, 1]

export const motionDuration = {
  instant: 0.16,
  control: 0.24,
  panel: 0.42,
  composition: 0.68,
}

export const motionSpring = {
  control: { type: 'spring', stiffness: 420, damping: 34, mass: 0.7 },
  layout: { type: 'spring', stiffness: 300, damping: 31, mass: 0.8 },
  panel: { type: 'spring', stiffness: 230, damping: 27, mass: 0.9 },
}

export const press = {
  whileHover: { y: -2 },
  whilePress: { scale: 0.975, y: 0 },
  transition: motionSpring.control,
}

export const listItem = {
  hidden: { opacity: 0, y: 16, filter: 'blur(6px)' },
  shown: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { duration: motionDuration.panel, ease: motionEase } },
  exit: { opacity: 0, scale: .98, transition: { duration: motionDuration.instant } },
}

export const reveal = (distance = 24, delay = 0) => ({
  initial: { opacity: 0, y: distance, filter: 'blur(8px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  transition: { duration: motionDuration.composition, delay, ease: motionEase },
})

export const stagger = (delayChildren = 0.08, staggerChildren = 0.07) => ({
  animate: { transition: { delayChildren, staggerChildren } },
})

export const childReveal = {
  initial: { opacity: 0, y: 18, filter: 'blur(7px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  transition: { duration: motionDuration.panel, ease: motionEase },
}

export const sportTransition = {
  initial: { opacity: 0, scale: 0.9, rotate: -9, filter: 'blur(10px)' },
  animate: { opacity: 1, scale: 1, rotate: 0, filter: 'blur(0px)' },
  exit: { opacity: 0, scale: 1.06, rotate: 7, filter: 'blur(8px)' },
  transition: { type: 'spring', stiffness: 120, damping: 19, mass: 0.9 },
}
