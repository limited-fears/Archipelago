import collections

from ..AutoWorld import World

from BaseClasses import Region, Entrance, Location, Item
from .Technologies import base_tech_table, recipe_sources, base_technology_table, advancement_technologies, \
    all_ingredient_names, all_product_sources, required_technologies, get_rocket_requirements, rocket_recipes, \
    progressive_technology_table, common_tech_table, tech_to_progressive_lookup, progressive_tech_table, \
    get_science_pack_pools, Recipe, recipes, technology_table, tech_table, factorio_base_id, useless_technologies
from .Shapes import get_shapes
from .Mod import generate_mod
from .Options import factorio_options, Silo

import logging


class FactorioItem(Item):
    game = "Factorio"


all_items = tech_table.copy()
all_items["Attack Trap"] = factorio_base_id - 1
all_items["Evolution Trap"] = factorio_base_id - 2


class Factorio(World):
    """
    Factorio is a game about automation. You play as an engineer who has crash landed on the planet
    Nauvis, an inhospitable world filled with dangerous creatures called biters. Build a factory,
    research new technologies, and become more efficient in your quest to build a rocket and return home.
    """
    game: str = "Factorio"
    static_nodes = {"automation", "logistics", "rocket-silo"}
    custom_recipes = {}
    additional_advancement_technologies = set()

    item_name_to_id = all_items
    location_name_to_id = base_tech_table

    data_version = 5

    def generate_basic(self):
        player = self.player
        want_progressives = collections.defaultdict(lambda: self.world.progressive[player].
                                                    want_progressives(self.world.random))
        skip_silo = self.world.silo[player].value == Silo.option_spawn
        evolution_traps_wanted = self.world.evolution_traps[player].value
        attack_traps_wanted = self.world.attack_traps[player].value
        traps_wanted = ["Evolution Trap"] * evolution_traps_wanted + ["Attack Trap"] * attack_traps_wanted
        self.world.random.shuffle(traps_wanted)
        for tech_name in base_tech_table:
            if traps_wanted and tech_name in useless_technologies:
                self.world.itempool.append(self.create_item(traps_wanted.pop()))
            elif skip_silo and tech_name == "rocket-silo":
                pass
            else:
                progressive_item_name = tech_to_progressive_lookup.get(tech_name, tech_name)
                want_progressive = want_progressives[progressive_item_name]
                item_name = progressive_item_name if want_progressive else tech_name
                tech_item = self.create_item(item_name)
                if tech_name in self.static_nodes:
                    self.world.get_location(tech_name, player).place_locked_item(tech_item)
                else:
                    self.world.itempool.append(tech_item)
        map_basic_settings = self.world.world_gen[player].value["basic"]
        if map_basic_settings.get("seed", None) is None:  # allow seed 0
            map_basic_settings["seed"] = self.world.slot_seeds[player].randint(0, 2 ** 32 - 1)  # 32 bit uint

        self.sending_visible = self.world.tech_tree_information[player] == Options.TechTreeInformation.option_full


    generate_output = generate_mod

    def create_regions(self):
        player = self.player
        menu = Region("Menu", None, "Menu", player, self.world)
        crash = Entrance(player, "Crash Land", menu)
        menu.exits.append(crash)
        nauvis = Region("Nauvis", None, "Nauvis", player, self.world)

        skip_silo = self.world.silo[self.player].value == Silo.option_spawn
        for tech_name, tech_id in base_tech_table.items():
            if skip_silo and tech_name == "rocket-silo":
                continue
            tech = Location(player, tech_name, tech_id, nauvis)
            nauvis.locations.append(tech)
            tech.game = "Factorio"
        location = Location(player, "Rocket Launch", None, nauvis)
        nauvis.locations.append(location)
        location.game = "Factorio"
        event = Item("Victory", True, None, player)
        event.game = "Factorio"
        self.world.push_item(location, event, False)
        location.event = location.locked = True
        for ingredient in self.world.max_science_pack[self.player].get_allowed_packs():
            location = Location(player, f"Automate {ingredient}", None, nauvis)
            location.game = "Factorio"
            nauvis.locations.append(location)
            event = Item(f"Automated {ingredient}", True, None, player)
            self.world.push_item(location, event, False)
            location.event = location.locked = True
        crash.connect(nauvis)
        self.world.regions += [menu, nauvis]

    def set_rules(self):
        world = self.world
        player = self.player
        self.custom_technologies = self.set_custom_technologies()
        self.set_custom_recipes()
        shapes = get_shapes(self)
        if world.logic[player] != 'nologic':
            from worlds.generic import Rules
            for ingredient in self.world.max_science_pack[self.player].get_allowed_packs():
                location = world.get_location(f"Automate {ingredient}", player)

                if self.world.recipe_ingredients[self.player]:
                    custom_recipe = self.custom_recipes[ingredient]

                    location.access_rule = lambda state, ingredient=ingredient, custom_recipe=custom_recipe: \
                        (ingredient not in technology_table or state.has(ingredient, player)) and \
                        all(state.has(technology.name, player) for sub_ingredient in custom_recipe.ingredients
                            for technology in required_technologies[sub_ingredient])
                else:
                    location.access_rule = lambda state, ingredient=ingredient: \
                        all(state.has(technology.name, player) for technology in required_technologies[ingredient])

            skip_silo = self.world.silo[self.player].value == Silo.option_spawn
            for tech_name, technology in self.custom_technologies.items():
                if skip_silo and tech_name == "rocket-silo":
                    continue
                location = world.get_location(tech_name, player)
                Rules.set_rule(location, technology.build_rule(player))
                prequisites = shapes.get(tech_name)
                if prequisites:
                    locations = {world.get_location(requisite, player) for requisite in prequisites}
                    Rules.add_rule(location, lambda state,
                                                    locations=locations: all(state.can_reach(loc) for loc in locations))

            silo_recipe = None if self.world.silo[self.player].value == Silo.option_spawn \
                else self.custom_recipes["rocket-silo"] \
                if "rocket-silo" in self.custom_recipes \
                else next(iter(all_product_sources.get("rocket-silo")))
            part_recipe = self.custom_recipes["rocket-part"]
            victory_tech_names = get_rocket_requirements(silo_recipe, part_recipe)
            world.get_location("Rocket Launch", player).access_rule = lambda state: all(state.has(technology, player)
                                                                                        for technology in
                                                                                        victory_tech_names)

        world.completion_condition[player] = lambda state: state.has('Victory', player)

    def collect_item(self, state, item, remove=False):
        if item.advancement and item.name in progressive_technology_table:
            prog_table = progressive_technology_table[item.name].progressive
            if remove:
                for item_name in reversed(prog_table):
                    if state.has(item_name, item.player):
                        return item_name
            else:
                for item_name in prog_table:
                    if not state.has(item_name, item.player):
                        return item_name

        return super(Factorio, self).collect_item(state, item, remove)

    def get_required_client_version(self) -> tuple:
        return max((0, 1, 6), super(Factorio, self).get_required_client_version())

    options = factorio_options

    def make_balanced_recipe(self, original: Recipe, pool: list, factor: float = 1) -> Recipe:
        """Generate a recipe from pool with time and cost similar to original * factor"""
        new_ingredients = {}
        self.world.random.shuffle(pool)
        target_raw = int(sum((count for ingredient, count in original.base_cost.items())) * factor)
        target_energy = original.total_energy * factor
        target_num_ingredients = len(original.ingredients)
        remaining_raw = target_raw
        remaining_energy = target_energy
        remaining_num_ingredients = target_num_ingredients
        fallback_pool = []

        # fill all but one slot with random ingredients, last with a good match
        while remaining_num_ingredients > 0 and len(pool) > 0:
            if remaining_num_ingredients == 1:
                max_raw = 1.1 * remaining_raw
                min_raw = 0.9 * remaining_raw
                max_energy = 1.1 * remaining_energy
                min_energy = 1.1 * remaining_energy
            else:
                max_raw = remaining_raw * 0.75
                min_raw = (remaining_raw - max_raw) / remaining_num_ingredients
                max_energy = remaining_energy * 0.75
                min_energy = (remaining_energy - max_energy) / remaining_num_ingredients
            ingredient = pool.pop()
            if ingredient in all_product_sources:
                ingredient_recipe = min(all_product_sources[ingredient], key=lambda recipe: recipe.rel_cost)
                ingredient_raw = sum((count for ingredient, count in ingredient_recipe.base_cost.items()))
                ingredient_energy = ingredient_recipe.total_energy
            else:
                # assume simple ore TODO: remove if tree when mining data is harvested from Factorio
                ingredient_raw = 1
                ingredient_energy = 2
            min_num_raw = min_raw / ingredient_raw
            max_num_raw = max_raw / ingredient_raw
            min_num_energy = min_energy / ingredient_energy
            max_num_energy = max_energy / ingredient_energy
            min_num = int(max(1, min_num_raw, min_num_energy))
            max_num = int(min(1000, max_num_raw, max_num_energy))
            if min_num > max_num:
                fallback_pool.append(ingredient)
                continue  # can't use that ingredient
            num = self.world.random.randint(min_num, max_num)
            new_ingredients[ingredient] = num
            remaining_raw -= num * ingredient_raw
            remaining_energy -= num * ingredient_energy
            remaining_num_ingredients -= 1

        # fill failed slots with whatever we got
        pool = fallback_pool
        while remaining_num_ingredients > 0 and len(pool) > 0:
            ingredient = pool.pop()
            if ingredient not in recipes:
                logging.warning(f"missing recipe for {ingredient}")
                continue
            ingredient_recipe = recipes[ingredient]
            ingredient_raw = sum((count for ingredient, count in ingredient_recipe.base_cost.items()))
            ingredient_energy = ingredient_recipe.total_energy
            num_raw = remaining_raw / ingredient_raw / remaining_num_ingredients
            num_energy = remaining_energy / ingredient_energy / remaining_num_ingredients
            num = int(min(num_raw, num_energy))
            if num < 1: continue
            new_ingredients[ingredient] = num
            remaining_raw -= num * ingredient_raw
            remaining_energy -= num * ingredient_energy
            remaining_num_ingredients -= 1

        if remaining_num_ingredients > 1:
            logging.warning("could not randomize recipe")

        return Recipe(original.name, original.category, new_ingredients, original.products, original.energy)

    def set_custom_technologies(self):
        custom_technologies = {}
        allowed_packs = self.world.max_science_pack[self.player].get_allowed_packs()
        for technology_name, technology in base_technology_table.items():
            custom_technologies[technology_name] = technology.get_custom(self.world, allowed_packs, self.player)
        return custom_technologies

    def set_custom_recipes(self):
        original_rocket_part = recipes["rocket-part"]
        science_pack_pools = get_science_pack_pools()
        valid_pool = sorted(science_pack_pools[self.world.max_science_pack[self.player].get_max_pack()])
        self.world.random.shuffle(valid_pool)
        self.custom_recipes = {"rocket-part": Recipe("rocket-part", original_rocket_part.category,
                                                     {valid_pool[x]: 10 for x in range(3)},
                                                     original_rocket_part.products,
                                                     original_rocket_part.energy)}
        self.additional_advancement_technologies = {tech.name for tech in
                                                    self.custom_recipes["rocket-part"].recursive_unlocking_technologies}

        if self.world.recipe_ingredients[self.player]:
            valid_pool = []
            for pack in self.world.max_science_pack[self.player].get_ordered_science_packs():
                valid_pool += sorted(science_pack_pools[pack])
                self.world.random.shuffle(valid_pool)
                if pack in recipes:  # skips over space science pack
                    original = recipes[pack]
                    new_ingredients = {}
                    for _ in original.ingredients:
                        new_ingredients[valid_pool.pop()] = 1
                    new_recipe = Recipe(pack, original.category, new_ingredients, original.products, original.energy)
                    self.additional_advancement_technologies |= {tech.name for tech in
                                                                 new_recipe.recursive_unlocking_technologies}
                    self.custom_recipes[pack] = new_recipe

        if self.world.silo[self.player].value == Silo.option_randomize_recipe:
            valid_pool = []
            for pack in sorted(self.world.max_science_pack[self.player].get_allowed_packs()):
                valid_pool += sorted(science_pack_pools[pack])
            new_recipe = self.make_balanced_recipe(recipes["rocket-silo"], valid_pool,
                                                   factor=(self.world.max_science_pack[self.player].value + 1) / 7)
            self.additional_advancement_technologies |= {tech.name for tech in
                                                         new_recipe.recursive_unlocking_technologies}
            self.custom_recipes["rocket-silo"] = new_recipe

        # handle marking progressive techs as advancement
        prog_add = set()
        for tech in self.additional_advancement_technologies:
            if tech in tech_to_progressive_lookup:
                prog_add.add(tech_to_progressive_lookup[tech])
        self.additional_advancement_technologies |= prog_add

    def create_item(self, name: str) -> Item:
        if name in tech_table:
            return FactorioItem(name, name in advancement_technologies or
                                name in self.additional_advancement_technologies,
                                tech_table[name], self.player)

        item = FactorioItem(name, False, all_items[name], self.player)
        if "Trap" in name:
            item.trap = True
        return item
