import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const MOBILE_BREAKPOINT = 760

const elementOf = value => value?.$el ?? value

export function useFloatingPanel({ open, trigger, panel, minimumWidth = 230 }) {
  const floatingStyle = ref({})
  const mobile = ref(false)
  let previousOverflow = ''

  const syncScrollLock = value => {
    if (typeof document === 'undefined') return
    if (value && mobile.value) {
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    } else if (document.body.style.overflow === 'hidden') {
      document.body.style.overflow = previousOverflow
    }
  }

  const measure = () => {
    if (typeof window === 'undefined') return
    mobile.value = window.innerWidth <= MOBILE_BREAKPOINT
    const triggerElement = elementOf(trigger.value)
    if (mobile.value || !open.value || !triggerElement) {
      floatingStyle.value = {}
      return
    }

    const rect = triggerElement.getBoundingClientRect()
    const gutter = 12
    const gap = 7
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const width = Math.min(Math.max(rect.width, minimumWidth), viewportWidth - gutter * 2)
    const left = Math.min(Math.max(rect.left, gutter), viewportWidth - width - gutter)
    const roomBelow = viewportHeight - rect.bottom - gutter - gap
    const roomAbove = rect.top - gutter - gap
    const placeAbove = roomBelow < 260 && roomAbove > roomBelow
    const maxHeight = Math.max(180, Math.min(420, placeAbove ? roomAbove : roomBelow))

    floatingStyle.value = placeAbove
      ? { left: `${left}px`, bottom: `${viewportHeight - rect.top + gap}px`, width: `${width}px`, maxHeight: `${maxHeight}px` }
      : { left: `${left}px`, top: `${rect.bottom + gap}px`, width: `${width}px`, maxHeight: `${maxHeight}px` }
  }

  watch(open, async value => {
    if (value) {
      mobile.value = window.innerWidth <= MOBILE_BREAKPOINT
      await nextTick()
      measure()
    }
    syncScrollLock(value)
  })

  const onViewportChange = () => {
    const wasMobile = mobile.value
    measure()
    if (open.value && wasMobile !== mobile.value) syncScrollLock(mobile.value)
  }

  onMounted(() => {
    mobile.value = window.innerWidth <= MOBILE_BREAKPOINT
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('scroll', measure, true)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', onViewportChange)
    window.removeEventListener('scroll', measure, true)
    syncScrollLock(false)
  })

  return { floatingStyle, mobile }
}
