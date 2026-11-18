"""The four prompt templates: ready-made starting points users pick from the client's menu."""

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.prompt()
    def section_assessment(state: str, shrp_id: str) -> str:
        """Assess one LTPP test section: what it is, how it has performed, what was done to it, and why."""
        return (
            f"Assess LTPP test section {shrp_id} in {state}.\n"
            "1. Start with get_section_report for the overview, then use the detail tools where something "
            "stands out.\n"
            "2. Describe the structure (get_layer_structure), traffic (get_traffic_summary) and climate zone.\n"
            "3. Show how roughness, rutting and cracking progressed (get_roughness_history, "
            "get_rutting_history, get_cracking_history) and flag anything LTPP marked as a possible anomaly.\n"
            "4. List the maintenance and rehabilitation treatments (get_treatment_history) and, for the main "
            "ones, the performance before and after (get_performance_around_treatment).\n"
            "Finish with a short verdict on how the pavement behaved and what likely drove it. Give units, "
            "the construction number each result belongs to, and pass on every caveat. Do not claim a "
            "treatment caused a change."
        )

    @mcp.prompt()
    def treatment_effectiveness_memo(treatment: str, measure: str = "iri", climate_zone: str = "wet-freeze") -> str:
        """Draft a short memo on how a treatment changed performance, comparing thick and thin asphalt."""
        return (
            f"Write a one-page memo on the effect of '{treatment}' on {measure}, in a {climate_zone} "
            "climate.\n"
            "1. Use compare_treatment_effect_across_groups with two groups in that climate: asphalt "
            "thicker than 6 in (min_ac_thickness_in=6) and asphalt of 3 in or less (max_ac_thickness_in=3). "
            "Then repeat with group_by='climate_zone' to see whether the pattern is specific to this climate.\n"
            "2. Report, per group, the number of treatments and sections with a valid before and after, the "
            "mean and median change, the share that improved, and how long after the treatment the 'after' "
            "value was taken.\n"
            "3. Say plainly where samples are small and that the comparison is observational.\n"
            "Lead with the headline finding. State the data release, the units and the pairing rule from "
            "the caveats."
        )

    @mcp.prompt()
    def climate_performance_brief(measure: str = "iri", pavement_class: str = "flexible") -> str:
        """Brief on how a pavement type performs across climate zones, with the climate differences."""
        return (
            f"Prepare a brief on how {pavement_class} pavements perform on {measure} in each climate zone.\n"
            f"1. compare_performance_by_group with measure='{measure}', pavement_class='{pavement_class}', "
            "group_by='climate_zone' and age_bin_years=5.\n"
            "2. compare_climate_between_groups for the wet-freeze and dry-no-freeze zones on air temperature, "
            "freeze index and precipitation, so the performance gap can be read against the climate gap.\n"
            "3. Count the sections behind each result with summarize_sections_by_group.\n"
            "Explain which age bins have too few sections to trust. Remind the reader that climate here is "
            "modelled yearly and monthly data for a grid cell, not on-site measurement."
        )

    @mcp.prompt()
    def material_quality_review(material: str = "asphalt", state: str = "") -> str:
        """Review a layer property across sections and how reliable the underlying values are."""
        scope = f" in {state}" if state else " nationwide"
        return (
            f"Review {material} layer properties{scope}.\n"
            f"1. summarize_material_by_group for material='{material}' (start with repr_thickness, then an "
            "important property such as air_voids_avg_wp or comp_strength), grouped by climate_zone and by "
            "layer_type.\n"
            "2. For two or three representative sections, get_property_variability to show the spread and the "
            "quality of the source of each value (measured, calculated or imputed; low or high variability).\n"
            "3. Point out properties whose values are mostly imputed or come from a single measurement.\n"
            "Give units, the number of layers and sections behind each statistic, and the caveats."
        )
