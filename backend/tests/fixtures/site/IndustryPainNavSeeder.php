<?php
/* Synthetic IndustryPainNavSeeder-shaped fixture */
class IndustryPainNavSeederFixture
{
    private function painNavMap(): array
    {
        return [
            'demo-food' => [
                ['tag' => '冻干制品复水性差', 'target_slug' => 'demo-freeze-drying'],
                ['tag' => '冷却效率低影响产能', 'target_slug' => 'demo-cooling'],
            ],
            'demo-semi' => [
                ['tag' => '颗粒污染导致良率下降', 'target_slug' => 'demo-etching'],
            ],
        ];
    }
}
