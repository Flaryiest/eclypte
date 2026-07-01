"use client"

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"
import { Check, ChevronDown } from "lucide-react"
import styles from "./studio.module.css"

export type SelectOption = { value: string; label: string; disabled?: boolean }

type SelectProps = {
    value: string
    onChange: (value: string) => void
    options: SelectOption[]
    placeholder?: string
    ariaLabel?: string
    disabled?: boolean
    compact?: boolean
    className?: string
}

// Accessible single-select combobox: a styled trigger + a themed popover listbox.
// Focus stays on the trigger; the highlighted option is tracked with
// aria-activedescendant (the standard select pattern), so keyboard and screen
// readers work without moving DOM focus into the list.
export function Select({
    value,
    onChange,
    options,
    placeholder = "Select…",
    ariaLabel,
    disabled = false,
    compact = false,
    className,
}: SelectProps) {
    const [open, setOpen] = useState(false)
    const [highlight, setHighlight] = useState(-1)
    const [openUp, setOpenUp] = useState(false)
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const triggerRef = useRef<HTMLButtonElement | null>(null)
    const optionRefs = useRef<(HTMLDivElement | null)[]>([])
    const typeahead = useRef("")
    const typeaheadTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const baseId = useId()
    const listId = `${baseId}-list`
    const optionId = (index: number) => `${baseId}-opt-${index}`

    const selectedIndex = options.findIndex((option) => option.value === value)
    const selected = selectedIndex >= 0 ? options[selectedIndex] : null

    // Close when a pointer goes down outside the component.
    useEffect(() => {
        if (!open) {
            return
        }
        const onPointerDown = (event: PointerEvent) => {
            if (!wrapperRef.current?.contains(event.target as Node)) {
                setOpen(false)
            }
        }
        document.addEventListener("pointerdown", onPointerDown, true)
        return () => document.removeEventListener("pointerdown", onPointerDown, true)
    }, [open])

    // Keep the highlighted option scrolled into view.
    useEffect(() => {
        if (open && highlight >= 0) {
            optionRefs.current[highlight]?.scrollIntoView({ block: "nearest" })
        }
    }, [open, highlight])

    useEffect(() => () => {
        if (typeaheadTimer.current) {
            clearTimeout(typeaheadTimer.current)
        }
    }, [])

    const openMenu = () => {
        if (disabled) {
            return
        }
        const rect = triggerRef.current?.getBoundingClientRect()
        if (rect) {
            const spaceBelow = window.innerHeight - rect.bottom
            setOpenUp(spaceBelow < 260 && rect.top > spaceBelow)
        }
        setHighlight(selectedIndex >= 0 ? selectedIndex : firstEnabled(options))
        setOpen(true)
    }

    const closeMenu = (refocus = true) => {
        setOpen(false)
        if (refocus) {
            triggerRef.current?.focus()
        }
    }

    const choose = (index: number) => {
        const option = options[index]
        if (!option || option.disabled) {
            return
        }
        onChange(option.value)
        closeMenu()
    }

    const runTypeahead = (char: string) => {
        const query = (typeahead.current + char).toLowerCase()
        typeahead.current = query
        if (typeaheadTimer.current) {
            clearTimeout(typeaheadTimer.current)
        }
        typeaheadTimer.current = setTimeout(() => {
            typeahead.current = ""
        }, 600)
        const index = options.findIndex(
            (option) => !option.disabled && option.label.toLowerCase().startsWith(query),
        )
        if (index >= 0) {
            setHighlight(index)
        }
    }

    const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
        if (disabled) {
            return
        }
        if (!open) {
            if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
                event.preventDefault()
                openMenu()
            }
            return
        }
        switch (event.key) {
            case "ArrowDown":
                event.preventDefault()
                setHighlight((current) => nextEnabled(options, current, 1))
                break
            case "ArrowUp":
                event.preventDefault()
                setHighlight((current) => nextEnabled(options, current, -1))
                break
            case "Home":
                event.preventDefault()
                setHighlight(firstEnabled(options))
                break
            case "End":
                event.preventDefault()
                setHighlight(lastEnabled(options))
                break
            case "Enter":
            case " ":
                event.preventDefault()
                if (highlight >= 0) {
                    choose(highlight)
                }
                break
            case "Escape":
                event.preventDefault()
                closeMenu()
                break
            case "Tab":
                closeMenu(false)
                break
            default:
                if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
                    runTypeahead(event.key)
                }
        }
    }

    return (
        <div
            ref={wrapperRef}
            className={`${styles.selectWrap} ${compact ? styles.selectWrapCompact : ""} ${className ?? ""}`}
        >
            <button
                ref={triggerRef}
                type="button"
                className={`${styles.selectTrigger} ${compact ? styles.selectCompact : ""} ${open ? styles.selectTriggerOpen : ""}`}
                role="combobox"
                aria-haspopup="listbox"
                aria-expanded={open}
                aria-controls={listId}
                aria-activedescendant={open && highlight >= 0 ? optionId(highlight) : undefined}
                aria-label={ariaLabel}
                disabled={disabled}
                onClick={() => (open ? closeMenu(false) : openMenu())}
                onKeyDown={onKeyDown}
            >
                <span className={selected ? styles.selectValue : styles.selectPlaceholder}>
                    {selected ? selected.label : placeholder}
                </span>
                <ChevronDown size={16} className={styles.selectChevron} aria-hidden />
            </button>
            {open && (
                <div
                    id={listId}
                    role="listbox"
                    aria-label={ariaLabel}
                    className={`${styles.selectPopover} ${openUp ? styles.selectPopoverUp : ""}`}
                >
                    {options.length === 0 ? (
                        <div className={styles.selectEmpty}>Nothing here yet</div>
                    ) : (
                        options.map((option, index) => {
                            const isSelected = option.value === value
                            const isActive = index === highlight
                            return (
                                <div
                                    key={option.value}
                                    ref={(element) => {
                                        optionRefs.current[index] = element
                                    }}
                                    id={optionId(index)}
                                    role="option"
                                    aria-selected={isSelected}
                                    aria-disabled={option.disabled || undefined}
                                    className={`${styles.selectOption} ${isActive ? styles.selectOptionActive : ""} ${isSelected ? styles.selectOptionSelected : ""}`}
                                    onMouseEnter={() => !option.disabled && setHighlight(index)}
                                    onClick={() => choose(index)}
                                >
                                    <span className={styles.selectOptionLabel}>{option.label}</span>
                                    {isSelected && <Check size={15} aria-hidden />}
                                </div>
                            )
                        })
                    )}
                </div>
            )}
        </div>
    )
}

function firstEnabled(options: SelectOption[]) {
    return options.findIndex((option) => !option.disabled)
}

function lastEnabled(options: SelectOption[]) {
    for (let i = options.length - 1; i >= 0; i -= 1) {
        if (!options[i].disabled) {
            return i
        }
    }
    return -1
}

// Step from `from` in `direction` (+1/-1), wrapping, to the next enabled option.
function nextEnabled(options: SelectOption[], from: number, direction: number) {
    const count = options.length
    if (count === 0) {
        return -1
    }
    let index = from
    for (let step = 0; step < count; step += 1) {
        index += direction
        if (index < 0) {
            index = count - 1
        } else if (index >= count) {
            index = 0
        }
        if (!options[index].disabled) {
            return index
        }
    }
    return from
}
